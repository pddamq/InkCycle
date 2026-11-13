"""扩展功能 API：看板、@引用、模板、备份、分支、会话、RAG、读者审校。"""
import json

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from .. import db, prompts
from ..agent import extract_json, _cap, _current_content, _chapter, _project
from ..backup import export_full_backup, export_project_backup, import_full_backup, import_project_backup
from ..branch import fork_project, list_branches
from ..dashboard import consistency_report, style_drift_report
from ..llm import chat, LLMError
from ..rag import index_project, semantic_search
from .agent_api import sse

router = APIRouter(tags=["meta"])


# ---------------------------------------------------------------- 上下文占用估算

@router.post("/api/context/estimate")
async def estimate_context(body: dict):
    """预览本次 AI 调用的上下文 token 占用（Cursor 式 breakdown）。"""
    body = body or {}
    feature = body.get("feature") or ""
    if feature == "chat":
        from ..context_usage import estimate_chat
        try:
            pid = int(body.get("project_id"))
            chid = int(body.get("chapter_id"))
        except (TypeError, ValueError):
            return {"total": 0, "limit": 128000, "percent": 0, "remaining": 128000, "items": []}
        return await estimate_chat(
            pid, chid,
            history=body.get("history") or body.get("messages"),
            references=body.get("references"),
            selection=body.get("selection"),
        )
    if feature == "interview":
        from ..context_usage import estimate_interview
        return estimate_interview(
            body.get("history") or [],
            body.get("history_notes") or "",
            int(body.get("history_through_index") or 0),
            compile_mode=bool(body.get("compile")),
        )
    if feature == "character_interview":
        from ..context_usage import estimate_character_interview
        try:
            pid = int(body.get("project_id"))
        except (TypeError, ValueError):
            return {"total": 0, "limit": 128000, "percent": 0, "remaining": 128000, "items": []}
        return estimate_character_interview(
            pid,
            body.get("history") or [],
            compile_mode=bool(body.get("compile")),
        )
    return {"total": 0, "limit": 128000, "percent": 0, "remaining": 128000, "items": []}


# ---------------------------------------------------------------- 会话

@router.get("/api/session/last")
def get_last_session():
    raw = db.query_one("SELECT value FROM config WHERE key='last_session'")
    return db.jload(raw["value"] if raw else None, {}) or {}


@router.post("/api/session/last")
def set_last_session(body: dict):
    db.execute(
        "INSERT INTO config(key, value) VALUES('last_session', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(body, ensure_ascii=False),),
    )
    return {"ok": True}


# ---------------------------------------------------------------- 访谈草稿（断点续访 / 继续生成蓝图）

@router.get("/api/interview/draft")
def get_interview_draft():
    raw = db.query_one("SELECT value FROM config WHERE key='interview_draft'")
    return db.jload(raw["value"] if raw else None, {}) or {}


@router.post("/api/interview/draft")
def save_interview_draft(body: dict):
    db.execute(
        "INSERT INTO config(key, value) VALUES('interview_draft', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(body, ensure_ascii=False),),
    )
    return {"ok": True}


@router.delete("/api/interview/draft")
def delete_interview_draft():
    db.execute("DELETE FROM config WHERE key='interview_draft'")
    return {"ok": True}


# ---------------------------------------------------------------- 项目 UI 草稿（角色设计、向导等断点续做）

def _project_draft_key(pid: int, name: str) -> str:
    safe = (name or "default").replace("/", "_")[:64]
    return f"project_draft:{pid}:{safe}"


@router.get("/api/projects/{pid}/drafts/{name}")
def get_project_draft(pid: int, name: str):
    from .projects import _need_project
    _need_project(pid)
    raw = db.query_one("SELECT value FROM config WHERE key=?", (_project_draft_key(pid, name),))
    return db.jload(raw["value"] if raw else None, {}) or {}


@router.post("/api/projects/{pid}/drafts/{name}")
def save_project_draft(pid: int, name: str, body: dict):
    from .projects import _need_project
    _need_project(pid)
    db.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_project_draft_key(pid, name), json.dumps(body, ensure_ascii=False)),
    )
    return {"ok": True}


@router.delete("/api/projects/{pid}/drafts/{name}")
def delete_project_draft(pid: int, name: str):
    from .projects import _need_project
    _need_project(pid)
    db.execute("DELETE FROM config WHERE key=?", (_project_draft_key(pid, name),))
    return {"ok": True}


# ---------------------------------------------------------------- AI 生成快照（轨迹/阶段进度，关程序可恢复）

def _gen_snapshot_key(name: str) -> str:
    safe = (name or "default").replace("/", "_")[:128]
    return f"gen_snapshot:{safe}"


@router.get("/api/generation-snapshots/{name}")
def get_generation_snapshot(name: str):
    raw = db.query_one("SELECT value FROM config WHERE key=?", (_gen_snapshot_key(name),))
    return db.jload(raw["value"] if raw else None, {}) or {}


@router.post("/api/generation-snapshots/{name}")
def save_generation_snapshot(name: str, body: dict):
    db.execute(
        "INSERT INTO config(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_gen_snapshot_key(name), json.dumps(body, ensure_ascii=False)),
    )
    return {"ok": True}


@router.delete("/api/generation-snapshots/{name}")
def delete_generation_snapshot(name: str):
    db.execute("DELETE FROM config WHERE key=?", (_gen_snapshot_key(name),))
    return {"ok": True}


# ---------------------------------------------------------------- 看板

@router.get("/api/projects/{pid}/dashboard")
def project_dashboard(pid: int):
    return consistency_report(pid)


@router.get("/api/projects/{pid}/style-drift")
def project_style_drift(pid: int):
    return style_drift_report(pid)


# ---------------------------------------------------------------- @ 引用

@router.get("/api/projects/{pid}/references")
def list_references(pid: int, q: str = ""):
    q = (q or "").strip().lower()
    items = []

    for c in db.query("SELECT id, name, role, profile FROM characters WHERE project_id=? ORDER BY name", (pid,)):
        if not q or q in c["name"].lower() or q in (c.get("role") or "").lower():
            prof = db.jload(c.get("profile"), {})
            items.append({
                "type": "character", "id": c["id"], "label": c["name"],
                "hint": c.get("role") or "",
                "content": json.dumps(prof, ensure_ascii=False)[:1200] if prof else c["name"],
            })

    world = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    for sec in db.jload(world["sections"] if world else None, []) or []:
        title = sec.get("title") or sec.get("name") or "设定"
        if not q or q in title.lower() or q in (sec.get("content") or "").lower():
            items.append({
                "type": "world", "id": title, "label": title,
                "hint": "世界观",
                "content": (sec.get("content") or "")[:1200],
            })

    for ch in db.query(
        "SELECT id, title, idx, brief FROM chapters WHERE project_id=? ORDER BY volume_id, idx", (pid,)):
        label = f"第{ch['idx']+1}章 {ch['title']}"
        if not q or q in label.lower() or q in (ch.get("brief") or "").lower():
            items.append({
                "type": "chapter", "id": ch["id"], "label": label,
                "hint": "章节梗概",
                "content": (ch.get("brief") or "（无梗概）")[:800],
            })

    for f in db.query(
        "SELECT id, description, status FROM foreshadowing WHERE project_id=? ORDER BY id DESC LIMIT 50", (pid,)):
        if not q or q in f["description"].lower():
            items.append({
                "type": "foreshadow", "id": f["id"], "label": f["description"][:40],
                "hint": f["status"],
                "content": f["description"],
            })

    return {"items": items[:30]}


# ---------------------------------------------------------------- 模板

@router.get("/api/interview/templates")
def get_templates():
    rows = db.query("SELECT id, name, category, blueprint, seed_history, is_builtin FROM interview_templates ORDER BY is_builtin DESC, id")
    for r in rows:
        r["blueprint"] = db.jload(r.get("blueprint"), {})
        r["seed_history"] = db.jload(r.get("seed_history"), [])
    return {"templates": rows}


@router.post("/api/interview/templates")
def save_template(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "缺少模板名"}
    tid = db.execute(
        "INSERT INTO interview_templates(name, category, blueprint, seed_history, is_builtin, created_at)"
        " VALUES(?,?,?,?,0,?)",
        (name, body.get("category", ""), json.dumps(body.get("blueprint") or {}, ensure_ascii=False),
         json.dumps(body.get("seed_history") or [], ensure_ascii=False), db.now()),
    )
    return {"ok": True, "id": tid}


# ---------------------------------------------------------------- 备份

@router.get("/api/backup/export")
def backup_export():
    data = export_full_backup()
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=novel-agent-backup.zip"})


@router.get("/api/projects/{pid}/backup/export")
def project_backup_export(pid: int):
    data = export_project_backup(pid)
    proj = db.query_one("SELECT title FROM projects WHERE id=?", (pid,))
    name = (proj["title"] if proj else "project").replace("/", "_")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={name}-backup.zip"})


@router.post("/api/backup/import")
async def backup_import(file: UploadFile = File(...)):
    data = await file.read()
    try:
        if data[:2] == b"PK":
            import zipfile, io
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "project.json" in zf.namelist():
                    new_id = import_project_backup(data)
                    return {"ok": True, "type": "project", "project_id": new_id}
        import_full_backup(data)
        return {"ok": True, "type": "full"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------- 分支

@router.post("/api/projects/{pid}/branch")
def create_branch(pid: int, body: dict):
    name = (body.get("branch_name") or body.get("name") or "分支").strip()
    return fork_project(pid, name, body.get("note") or "")


@router.get("/api/projects/{pid}/branches")
def get_branches(pid: int):
    return list_branches(pid)


# ---------------------------------------------------------------- RAG

@router.post("/api/projects/{pid}/rag/index")
def rag_index(pid: int, body: dict = None):
    body = body or {}
    n = index_project(pid, body.get("chapter_id"))
    return {"ok": True, "chunks": n}


@router.get("/api/projects/{pid}/rag/search")
def rag_search(pid: int, q: str, limit: int = 8, exclude_chapter_id: int = None):
    return {"hits": semantic_search(pid, q, limit=limit, exclude_chapter_id=exclude_chapter_id)}


# ---------------------------------------------------------------- 读者视角审校

@router.post("/api/projects/{pid}/chapters/{chid}/reader-review")
async def reader_review(pid: int, chid: int, body: dict = None):
    body = body or {}

    async def gen():
        chapter = _chapter(chid)
        project = _project(pid)
        if not chapter or not project:
            yield {"type": "error", "message": "章节不存在"}
            return
        persona = body.get("persona") or "目标读者"
        content = _current_content(chapter)
        if not content:
            yield {"type": "error", "message": "本章暂无正文"}
            return
        yield {"type": "status", "message": f"以「{persona}」视角阅读中…"}
        try:
            raw = await chat([
                {"role": "system", "content": prompts.READER_REVIEW_SYSTEM},
                {"role": "user", "content": prompts.READER_REVIEW_USER.format(
                    persona=persona, genre=project.get("genre") or "未指定",
                    audience=db.jload(project.get("brief"), {}).get("audience") or "一般读者",
                    title=chapter["title"], content=_cap(content, 6000),
                )},
            ])
            report = extract_json(raw) or {}
            yield {"type": "reader_review", "persona": persona, "report": report, "raw": raw[:500]}
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
        yield {"type": "done", "stage": "reader_review"}

    return sse(gen())
