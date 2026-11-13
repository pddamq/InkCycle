"""项目/世界观/角色/卷章/版本/伏笔/时间线/统计/导出 的 CRUD。"""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .. import db, exporter
from ..project_context import save_creation_notes

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _need_project(pid: int) -> dict:
    row = db.query_one("SELECT * FROM projects WHERE id=?", (pid,))
    if not row:
        raise HTTPException(404, "项目不存在")
    return row


def _touch(pid: int):
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))


# ---------------------------------------------------------------- 项目

@router.get("")
def list_projects():
    rows = db.query("SELECT * FROM projects ORDER BY updated_at DESC")
    out = []
    for r in rows:
        stats = _stats(r["id"])
        out.append({**r, "brief": db.jload(r.get("brief"), {}), "stats": stats})
    return out


@router.post("")
def create_project(body: dict):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "书名不能为空")
    brief = body.get("brief")
    if isinstance(brief, dict):
        brief = json.dumps(brief, ensure_ascii=False)
    elif not isinstance(brief, str):
        brief = "{}"
    pid = db.execute(
        "INSERT INTO projects(title, genre, premise, style, target_words, brief, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (title, body.get("genre", ""), body.get("premise", ""), body.get("style", ""),
         int(body.get("target_words") or 200000), brief, db.now(), db.now()),
    )
    db.execute("INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?)",
               (pid, "[]", db.now()))
    if body.get("interview_history") or body.get("interview_transcript"):
        save_creation_notes(pid, body.get("interview_history") or [], body.get("interview_transcript"))
    return {"id": pid}


@router.get("/{pid}")
def get_project(pid: int):
    row = _need_project(pid)
    world = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    return {**row, "brief": db.jload(row.get("brief"), {}),
            "world": db.jload(world["sections"], []) if world else [],
            "stats": _stats(pid)}


@router.put("/{pid}")
def update_project(pid: int, body: dict):
    _need_project(pid)
    fields = {"title", "genre", "premise", "style", "target_words", "status"}
    sets, args = [], []
    for f in fields:
        if f in body:
            sets.append(f"{f}=?")
            args.append(body[f])
    if "brief" in body:
        brief = body["brief"]
        if isinstance(brief, dict):
            brief = json.dumps(brief, ensure_ascii=False)
        elif not isinstance(brief, str):
            brief = "{}"
        sets.append("brief=?")
        args.append(brief)
    if sets:
        sets.append("updated_at=?")
        args.append(db.now())
        args.append(pid)
        db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", tuple(args))
    return {"ok": True}


@router.delete("/{pid}")
def delete_project(pid: int):
    _need_project(pid)
    for sql, arg in [
        ("DELETE FROM chapter_versions WHERE chapter_id IN (SELECT id FROM chapters WHERE project_id=?)", pid),
        ("DELETE FROM reviews WHERE chapter_id IN (SELECT id FROM chapters WHERE project_id=?)", pid),
        ("DELETE FROM chapters WHERE project_id=?", pid),
        ("DELETE FROM volumes WHERE project_id=?", pid),
        ("DELETE FROM characters WHERE project_id=?", pid),
        ("DELETE FROM foreshadowing WHERE project_id=?", pid),
        ("DELETE FROM timeline_events WHERE project_id=?", pid),
        ("DELETE FROM world WHERE project_id=?", pid),
        ("DELETE FROM projects WHERE id=?", pid),
    ]:
        db.execute(sql, (arg,))
    return {"ok": True}


@router.get("/{pid}/stats")
def stats(pid: int):
    _need_project(pid)
    return _stats(pid)


def _stats(pid: int) -> dict:
    total_ch = db.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(word_count),0) AS w FROM chapters WHERE project_id=?",
        (pid,),
    )
    done_ch = db.query_one(
        "SELECT COUNT(*) AS n FROM chapters WHERE project_id=? AND current_version_id IS NOT NULL",
        (pid,),
    )
    n_chars = db.query_one("SELECT COUNT(*) AS n FROM characters WHERE project_id=?", (pid,))["n"]
    fo = db.query_one(
        "SELECT SUM(status='open') AS open, SUM(status='paid') AS paid FROM foreshadowing WHERE project_id=?",
        (pid,),
    )
    return {
        "chapters": total_ch["n"],
        "chapters_done": done_ch["n"],
        "words": total_ch["w"],
        "characters": n_chars,
        "foreshadow_open": int(fo["open"] or 0),
        "foreshadow_paid": int(fo["paid"] or 0),
    }


# ---------------------------------------------------------------- 世界观

@router.get("/{pid}/world")
def get_world(pid: int):
    _need_project(pid)
    row = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    return db.jload(row["sections"], []) if row else []


@router.put("/{pid}/world")
def put_world(pid: int, body: dict):
    _need_project(pid)
    sections = body.get("sections")
    if not isinstance(sections, list):
        raise HTTPException(400, "sections 须为数组")
    db.execute(
        "INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(project_id) DO UPDATE SET sections=excluded.sections, updated_at=excluded.updated_at",
        (pid, json.dumps(sections, ensure_ascii=False), db.now()),
    )
    _touch(pid)
    return {"ok": True}


# ---------------------------------------------------------------- 角色

@router.get("/{pid}/characters")
def list_characters(pid: int):
    _need_project(pid)
    rows = db.query("SELECT * FROM characters WHERE project_id=? ORDER BY id", (pid,))
    for r in rows:
        r["profile"] = db.jload(r["profile"], {})
    return rows


@router.post("/{pid}/characters")
def create_character(pid: int, body: dict):
    _need_project(pid)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    cid = db.execute(
        "INSERT INTO characters(project_id, name, role, profile, created_at, updated_at) VALUES(?,?,?,?,?,?)",
        (pid, name, body.get("role", ""), json.dumps(body.get("profile", {}), ensure_ascii=False),
         db.now(), db.now()),
    )
    _touch(pid)
    return {"id": cid}


@router.put("/{pid}/characters/{cid}")
def update_character(pid: int, cid: int, body: dict):
    row = db.query_one("SELECT id FROM characters WHERE id=? AND project_id=?", (cid, pid))
    if not row:
        raise HTTPException(404, "角色不存在")
    sets, args = [], []
    if "name" in body:
        sets.append("name=?")
        args.append(body["name"])
    if "role" in body:
        sets.append("role=?")
        args.append(body["role"])
    if "profile" in body:
        sets.append("profile=?")
        args.append(json.dumps(body["profile"], ensure_ascii=False))
    if sets:
        sets.append("updated_at=?")
        args.append(db.now())
        args.append(cid)
        db.execute(f"UPDATE characters SET {', '.join(sets)} WHERE id=?", tuple(args))
        _touch(pid)
    return {"ok": True}


@router.delete("/{pid}/characters/{cid}")
def delete_character(pid: int, cid: int):
    db.execute("DELETE FROM characters WHERE id=? AND project_id=?", (cid, pid))
    return {"ok": True}


# ---------------------------------------------------------------- 卷与章

@router.get("/{pid}/outline")
def get_outline(pid: int):
    _need_project(pid)
    vols = db.query("SELECT * FROM volumes WHERE project_id=? ORDER BY idx, id", (pid,))
    chs = db.query("SELECT * FROM chapters WHERE project_id=? ORDER BY volume_id, idx, id", (pid,))
    by_vol = {}
    for ch in chs:
        by_vol.setdefault(ch["volume_id"], []).append({
            "id": ch["id"], "idx": ch["idx"], "title": ch["title"], "brief": ch["brief"],
            "status": ch["status"], "word_count": ch["word_count"],
            "summary": ch["summary"], "has_content": ch["current_version_id"] is not None,
        })
    return [{"id": v["id"], "idx": v["idx"], "title": v["title"], "summary": v["summary"],
             "chapters": by_vol.get(v["id"], [])} for v in vols]


@router.post("/{pid}/volumes")
def create_volume(pid: int, body: dict):
    _need_project(pid)
    mx = db.query_one("SELECT COALESCE(MAX(idx),-1) AS m FROM volumes WHERE project_id=?", (pid,))["m"]
    vid = db.execute(
        "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
        (pid, mx + 1, body.get("title", "新卷"), body.get("summary", "")),
    )
    _touch(pid)
    return {"id": vid}


@router.put("/{pid}/volumes/{vid}")
def update_volume(pid: int, vid: int, body: dict):
    row = db.query_one("SELECT id FROM volumes WHERE id=? AND project_id=?", (vid, pid))
    if not row:
        raise HTTPException(404, "卷不存在")
    sets, args = [], []
    if "title" in body:
        sets.append("title=?")
        args.append(body["title"])
    if "summary" in body:
        sets.append("summary=?")
        args.append(body["summary"])
    if "idx" in body:
        sets.append("idx=?")
        args.append(int(body["idx"]))
    if sets:
        args.append(vid)
        db.execute(f"UPDATE volumes SET {', '.join(sets)} WHERE id=?", tuple(args))
        _touch(pid)
    return {"ok": True}


@router.delete("/{pid}/volumes/{vid}")
def delete_volume(pid: int, vid: int, cascade: bool = True):
    row = db.query_one("SELECT id FROM volumes WHERE id=? AND project_id=?", (vid, pid))
    if not row:
        raise HTTPException(404, "卷不存在")
    chs = db.query("SELECT id FROM chapters WHERE volume_id=?", (vid,))
    if cascade:
        for ch in chs:
            db.execute("DELETE FROM chapter_versions WHERE chapter_id=?", (ch["id"],))
            db.execute("DELETE FROM reviews WHERE chapter_id=?", (ch["id"],))
        db.execute("DELETE FROM chapters WHERE volume_id=?", (vid,))
    else:
        # 挪到第一卷
        first = db.query_one("SELECT id FROM volumes WHERE project_id=? ORDER BY idx LIMIT 1", (pid,))
        if first and first["id"] != vid:
            db.execute("UPDATE chapters SET volume_id=? WHERE volume_id=?", (first["id"], vid))
    db.execute("DELETE FROM volumes WHERE id=?", (vid,))
    _touch(pid)
    return {"ok": True}


@router.post("/{pid}/chapters")
def create_chapter(pid: int, body: dict):
    _need_project(pid)
    vid = body.get("volume_id")
    vol = db.query_one("SELECT id FROM volumes WHERE id=? AND project_id=?", (vid, pid))
    if not vol:
        raise HTTPException(400, "volume_id 无效")
    title = (body.get("title") or "").strip() or "新章节"
    mx = db.query_one(
        "SELECT COALESCE(MAX(idx),-1) AS m FROM chapters WHERE volume_id=?", (vid,)
    )["m"]
    cid = db.execute(
        "INSERT INTO chapters(project_id, volume_id, idx, title, brief, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (pid, vid, mx + 1, title, body.get("brief", ""), db.now(), db.now()),
    )
    _touch(pid)
    return {"id": cid}


@router.put("/{pid}/chapters/{chid}")
def update_chapter(pid: int, chid: int, body: dict):
    ch = db.query_one("SELECT * FROM chapters WHERE id=? AND project_id=?", (chid, pid))
    if not ch:
        raise HTTPException(404, "章节不存在")
    sets, args = [], []
    if "title" in body:
        sets.append("title=?")
        args.append(body["title"])
    if "brief" in body:
        sets.append("brief=?")
        args.append(body["brief"])
    if "volume_id" in body and body["volume_id"] != ch["volume_id"]:
        vol = db.query_one("SELECT id FROM volumes WHERE id=? AND project_id=?", (body["volume_id"], pid))
        if not vol:
            raise HTTPException(400, "volume_id 无效")
        sets.append("volume_id=?")
        args.append(body["volume_id"])
    if "status" in body:
        sets.append("status=?")
        args.append(body["status"])
    if "summary" in body:
        sets.append("summary=?")
        args.append(body["summary"][:300])
    if "content" in body:
        content = body["content"]
        if content is not None and content != _current_content(ch):
            from ..agent import _save_version
            _save_version(chid, "manual", content, note="手动编辑")
            try:
                from ..rag import index_project
                index_project(pid, chid)
            except Exception:
                pass
    if sets:
        sets.append("updated_at=?")
        args.append(db.now())
        args.append(chid)
        db.execute(f"UPDATE chapters SET {', '.join(sets)} WHERE id=?", tuple(args))
        _touch(pid)
    ch = db.query_one("SELECT * FROM chapters WHERE id=?", (chid,))
    return {"ok": True, "word_count": ch["word_count"], "status": ch["status"],
            "current_version_id": ch["current_version_id"]}


def _current_content(ch):
    if not ch.get("current_version_id"):
        return ""
    ver = db.query_one("SELECT content FROM chapter_versions WHERE id=?", (ch["current_version_id"],))
    return ver["content"] if ver else ""


@router.delete("/{pid}/chapters/{chid}")
def delete_chapter(pid: int, chid: int):
    db.execute("DELETE FROM chapter_versions WHERE chapter_id=?", (chid,))
    db.execute("DELETE FROM reviews WHERE chapter_id=?", (chid,))
    db.execute("DELETE FROM chapters WHERE id=? AND project_id=?", (chid, pid))
    _touch(pid)
    return {"ok": True}


@router.get("/{pid}/chapters/{chid}")
def get_chapter(pid: int, chid: int):
    ch = db.query_one("SELECT * FROM chapters WHERE id=? AND project_id=?", (chid, pid))
    if not ch:
        raise HTTPException(404, "章节不存在")
    content = _current_content(ch)
    review = db.query_one(
        "SELECT * FROM reviews WHERE chapter_id=? ORDER BY id DESC LIMIT 1", (chid,)
    )
    return {
        "id": ch["id"], "volume_id": ch["volume_id"], "idx": ch["idx"], "title": ch["title"],
        "brief": ch["brief"], "status": ch["status"], "summary": ch["summary"],
        "word_count": ch["word_count"], "current_version_id": ch["current_version_id"],
        "content": content,
        "last_review": ({
            "id": review["id"], "score": review["score"], "round": review["round"],
            "report": db.jload(review["report"], {}), "created_at": review["created_at"],
        } if review else None),
    }


# ---------------------------------------------------------------- 版本历史

@router.get("/{pid}/chapters/{chid}/versions")
def list_versions(pid: int, chid: int):
    ch = db.query_one("SELECT current_version_id FROM chapters WHERE id=? AND project_id=?", (chid, pid))
    if not ch:
        raise HTTPException(404, "章节不存在")
    rows = db.query(
        "SELECT id, vtype, word_count, note, created_at FROM chapter_versions "
        "WHERE chapter_id=? ORDER BY id DESC",
        (chid,),
    )
    for r in rows:
        r["is_current"] = r["id"] == ch["current_version_id"]
    return rows


@router.get("/{pid}/chapters/{chid}/versions/{vid}")
def get_version(pid: int, chid: int, vid: int):
    ver = db.query_one("SELECT * FROM chapter_versions WHERE id=? AND chapter_id=?", (vid, chid))
    if not ver:
        raise HTTPException(404, "版本不存在")
    return ver


@router.post("/{pid}/chapters/{chid}/versions/{vid}/restore")
def restore_version(pid: int, chid: int, vid: int):
    ver = db.query_one("SELECT * FROM chapter_versions WHERE id=? AND chapter_id=?", (vid, chid))
    if not ver:
        raise HTTPException(404, "版本不存在")
    from ..agent import _save_version
    saved = _save_version(chid, "restore", ver["content"], note=f"回滚自版本 #{vid}")
    return saved


# ---------------------------------------------------------------- 审校历史

@router.get("/{pid}/chapters/{chid}/reviews")
def list_reviews(pid: int, chid: int):
    rows = db.query(
        "SELECT id, round, score, report, version_id, created_at FROM reviews "
        "WHERE chapter_id=? ORDER BY id DESC",
        (chid,),
    )
    for r in rows:
        r["report"] = db.jload(r["report"], {})
    return rows


# ---------------------------------------------------------------- 伏笔

@router.get("/{pid}/foreshadow")
def list_foreshadow(pid: int):
    _need_project(pid)
    rows = db.query(
        "SELECT f.*, pc.title AS planted_title, oc.title AS payoff_title FROM foreshadowing f "
        "LEFT JOIN chapters pc ON pc.id=f.planted_chapter_id "
        "LEFT JOIN chapters oc ON oc.id=f.payoff_chapter_id "
        "WHERE f.project_id=? ORDER BY f.id",
        (pid,),
    )
    return rows


@router.post("/{pid}/foreshadow")
def create_foreshadow(pid: int, body: dict):
    _need_project(pid)
    desc = (body.get("description") or "").strip()
    if not desc:
        raise HTTPException(400, "伏笔描述不能为空")
    fid = db.execute(
        "INSERT INTO foreshadowing(project_id, description, planted_chapter_id, status, note, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (pid, desc, body.get("planted_chapter_id"), "open", body.get("note", ""), db.now()),
    )
    _touch(pid)
    return {"id": fid}


@router.put("/{pid}/foreshadow/{fid}")
def update_foreshadow(pid: int, fid: int, body: dict):
    row = db.query_one("SELECT id FROM foreshadowing WHERE id=? AND project_id=?", (fid, pid))
    if not row:
        raise HTTPException(404, "伏笔不存在")
    sets, args = [], []
    if "description" in body:
        sets.append("description=?")
        args.append(body["description"])
    if "planted_chapter_id" in body:
        sets.append("planted_chapter_id=?")
        args.append(body["planted_chapter_id"])
    if "status" in body:
        sets.append("status=?")
        args.append(body["status"])
    if "payoff_chapter_id" in body:
        sets.append("payoff_chapter_id=?")
        args.append(body["payoff_chapter_id"])
        if body["payoff_chapter_id"]:
            sets.append("status=?")
            args.append("paid")
    if "note" in body:
        sets.append("note=?")
        args.append(body["note"])
    if sets:
        args.append(fid)
        db.execute(f"UPDATE foreshadowing SET {', '.join(sets)} WHERE id=?", tuple(args))
        _touch(pid)
    return {"ok": True}


@router.delete("/{pid}/foreshadow/{fid}")
def delete_foreshadow(pid: int, fid: int):
    db.execute("DELETE FROM foreshadowing WHERE id=? AND project_id=?", (fid, pid))
    return {"ok": True}


# ---------------------------------------------------------------- 时间线

@router.get("/{pid}/timeline")
def list_timeline(pid: int):
    _need_project(pid)
    return db.query(
        "SELECT t.*, c.title AS chapter_title FROM timeline_events t "
        "LEFT JOIN chapters c ON c.id=t.chapter_id "
        "WHERE t.project_id=? ORDER BY t.idx, t.id",
        (pid,),
    )


@router.post("/{pid}/timeline")
def create_timeline(pid: int, body: dict):
    _need_project(pid)
    desc = (body.get("description") or "").strip()
    if not desc:
        raise HTTPException(400, "事件描述不能为空")
    mx = db.query_one("SELECT COALESCE(MAX(idx),-1) AS m FROM timeline_events WHERE project_id=?", (pid,))["m"]
    eid = db.execute(
        "INSERT INTO timeline_events(project_id, chapter_id, time_label, description, idx, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (pid, body.get("chapter_id"), body.get("time_label", ""), desc, mx + 1, db.now()),
    )
    _touch(pid)
    return {"id": eid}


@router.put("/{pid}/timeline/{eid}")
def update_timeline(pid: int, eid: int, body: dict):
    row = db.query_one("SELECT id FROM timeline_events WHERE id=? AND project_id=?", (eid, pid))
    if not row:
        raise HTTPException(404, "事件不存在")
    sets, args = [], []
    for f in ("time_label", "description"):
        if f in body:
            sets.append(f"{f}=?")
            args.append(body[f])
    if "chapter_id" in body:
        sets.append("chapter_id=?")
        args.append(body["chapter_id"])
    if "idx" in body:
        sets.append("idx=?")
        args.append(int(body["idx"]))
    if sets:
        args.append(eid)
        db.execute(f"UPDATE timeline_events SET {', '.join(sets)} WHERE id=?", tuple(args))
        _touch(pid)
    return {"ok": True}


@router.delete("/{pid}/timeline/{eid}")
def delete_timeline(pid: int, eid: int):
    db.execute("DELETE FROM timeline_events WHERE id=? AND project_id=?", (eid, pid))
    return {"ok": True}


# ---------------------------------------------------------------- 导出

@router.get("/{pid}/export")
def export_project(pid: int, format: str = "md", scope: str = "book", scope_id: int = None):
    _need_project(pid)
    format = "md" if format == "md" else "txt"
    fname, text = exporter.build_export(pid, format, scope, scope_id)
    resp = PlainTextResponse(text)
    for k, v in exporter.download_headers(fname, format).items():
        resp.headers[k] = v
    resp.headers["Content-Type"] = ("text/markdown; charset=utf-8" if format == "md"
                                    else "text/plain; charset=utf-8")
    return resp


# ---------------------------------------------------------------- 剧情流程图

@router.get("/{pid}/plot-graph")
def plot_graph(pid: int):
    """聚合可视化剧情流程图所需的全部数据：
    卷、章节节点（含状态/字数/梗概/摘要/出场角色/伏笔埋设与回收/时间线事件数）、
    伏笔连线（埋设→回收）、角色清单。"""
    _need_project(pid)
    volumes = db.query("SELECT * FROM volumes WHERE project_id=? ORDER BY idx, id", (pid,))
    chapters = db.query(
        "SELECT * FROM chapters WHERE project_id=? ORDER BY volume_id, idx, id", (pid,))
    chars = db.query("SELECT id, name FROM characters WHERE project_id=? ORDER BY id", (pid,))
    foreshadows = db.query("SELECT * FROM foreshadowing WHERE project_id=? ORDER BY id", (pid,))
    tl_rows = db.query(
        "SELECT chapter_id, COUNT(*) AS n FROM timeline_events WHERE project_id=? GROUP BY chapter_id",
        (pid,))
    tl_map = {r["chapter_id"]: r["n"] for r in tl_rows}

    nodes = []
    for ch in chapters:
        content = ""
        if ch["current_version_id"]:
            ver = db.query_one(
                "SELECT content FROM chapter_versions WHERE id=?", (ch["current_version_id"],))
            content = ver["content"] if ver else ""
        appearing = [c["name"] for c in chars if c["name"] and c["name"] in content]
        planted = [f["id"] for f in foreshadows if f["planted_chapter_id"] == ch["id"]]
        resolved = [f["id"] for f in foreshadows if f["payoff_chapter_id"] == ch["id"]]
        nodes.append({
            "id": ch["id"], "volume_id": ch["volume_id"], "idx": ch["idx"],
            "title": ch["title"], "brief": ch["brief"], "summary": ch["summary"],
            "status": ch["status"], "word_count": ch["word_count"],
            "has_content": ch["current_version_id"] is not None,
            "characters": appearing,
            "foreshadow_planted": planted,
            "foreshadow_resolved": resolved,
            "timeline_count": tl_map.get(ch["id"], 0),
        })

    return {
        "volumes": [{"id": v["id"], "idx": v["idx"], "title": v["title"], "summary": v["summary"]}
                    for v in volumes],
        "nodes": nodes,
        "foreshadows": [{
            "id": f["id"], "description": f["description"],
            "planted_chapter_id": f["planted_chapter_id"],
            "payoff_chapter_id": f["payoff_chapter_id"], "status": f["status"],
        } for f in foreshadows],
        "characters": [{"id": c["id"], "name": c["name"]} for c in chars],
    }
