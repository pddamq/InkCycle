"""Agent SSE 接口：起草 / 审校 / 修订 / 自动循环 / 向导三步生成 / 手动摘要。"""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .. import db, prompts
from ..agent import run_draft, run_review, run_revise, run_auto, run_chat, extract_json, count_words
from ..llm import stream_chat, LLMError, stream_progress_hint
from ..project_context import (
    assemble, brief_block, cap as _cap, render_history as _render_history,
    world_digest as _world_digest, BRIEF_LABELS, BRIEF_KEYS,
)

router = APIRouter(prefix="/api/projects", tags=["agent"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse(agen):
    async def gen():
        try:
            async for ev in agen:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # 兜底：任何异常都转为 error 事件
            yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers=dict(SSE_HEADERS))


@router.post("/{pid}/chapters/{chid}/draft")
async def draft_chapter(pid: int, chid: int):
    return sse(run_draft(pid, chid))


@router.post("/{pid}/chapters/{chid}/review")
async def review_chapter(pid: int, chid: int):
    return sse(run_review(pid, chid))


@router.post("/{pid}/chapters/{chid}/revise")
async def revise_chapter(pid: int, chid: int):
    return sse(run_revise(pid, chid))


@router.post("/{pid}/chapters/{chid}/auto")
async def auto_chapter(pid: int, chid: int, body: dict = None):
    body = body or {}
    return sse(run_auto(pid, chid, rounds=body.get("rounds"), mode=body.get("mode", "full")))


@router.post("/{pid}/chapters/{chid}/chat")
async def chat_chapter(pid: int, chid: int, body: dict = None):
    """Cursor 式对话写作（SSE）。"""
    body = body or {}
    return sse(run_chat(
        pid, chid, body.get("messages") or [],
        references=body.get("references"),
        selection=body.get("selection"),
    ))


@router.post("/{pid}/chapters/{chid}/summarize")
async def summarize_chapter(pid: int, chid: int):
    ch = db.query_one("SELECT * FROM chapters WHERE id=? AND project_id=?", (chid, pid))
    if not ch:
        raise_ = {"type": "error", "message": "章节不存在"}
        return sse(_single(raise_))
    from ..agent import _current_content, _cap
    content = _current_content(ch)
    if not content:
        return sse(_single({"type": "error", "message": "本章暂无正文"}))

    async def gen():
        try:
            summary = await chat([
                {"role": "system", "content": prompts.SUMMARY_SYSTEM},
                {"role": "user", "content": prompts.SUMMARY_USER.format(
                    brief=_cap(ch["brief"], 300), content=_cap(content, 3000))},
            ])
            db.execute("UPDATE chapters SET summary=? WHERE id=?", (summary[:300], chid))
            yield {"type": "done", "summary": summary[:300]}
        except LLMError as e:
            yield {"type": "error", "message": str(e)}

    return sse(gen())


def _single(ev):
    async def gen():
        yield ev
    return gen()


# ---------------------------------------------------------------- 创作向导

def _project(pid):
    return db.query_one("SELECT * FROM projects WHERE id=?", (pid,))


def _brief_block(project, stage):
    return brief_block(project, stage)


async def _stream_wizard_llm(messages, *, status_msg: str):
    """向导类任务：流式推送思考/进度，末尾 yield _end 携带完整原文（勿展示给前端）。"""
    yield {"type": "status", "message": status_msg}
    parts = []
    try:
        async for ev in stream_chat(messages):
            if ev["type"] == "reasoning":
                yield ev
            elif ev["type"] == "text":
                parts.append(ev["text"])
                full = "".join(parts)
                yield {
                    "type": "progress",
                    "chars": len(full),
                    "hint": stream_progress_hint(full),
                }
    except LLMError as e:
        yield {"type": "error", "message": str(e)}
        yield {"type": "_end", "raw": ""}
        return
    yield {"type": "status", "message": "正在解析结果…"}
    yield {"type": "_end", "raw": "".join(parts)}


def _save_characters_from_json(pid, data, *, replace=False):
    """解析 LLM 返回的角色 JSON 数组并写入数据库。replace=True 时覆盖现有角色。"""
    if not data or not isinstance(data, list):
        return None
    if replace:
        db.execute("DELETE FROM characters WHERE project_id=?", (pid,))
    ids = []
    for c in data:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        cid = db.execute(
            "INSERT INTO characters(project_id, name, role, profile, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (pid, str(c["name"]), str(c.get("role", "")),
             json.dumps({k: v for k, v in c.items() if k not in ("name", "role")}, ensure_ascii=False),
             db.now(), db.now()),
        )
        ids.append(cid)
    if ids:
        db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
    return ids


async def _stream_generate_characters(pid, *, replace=False):
    project = _project(pid)
    if not project:
        yield {"type": "error", "message": "项目不存在"}
        return
    n = db.query_one("SELECT COUNT(*) AS n FROM characters WHERE project_id=?", (pid,))["n"]
    if n > 0 and not replace:
        yield {"type": "error", "message": "已有角色；如需重新生成请确认覆盖"}
        return
    ctx = assemble(pid, "wizard_characters").for_template()
    messages = [
        {"role": "system", "content": prompts.WIZARD_CHARACTERS_SYSTEM},
        {"role": "user", "content": prompts.WIZARD_CHARACTERS_USER.format(**ctx)},
    ]
    raw = ""
    async for ev in _stream_wizard_llm(messages, status_msg="正在设计主要角色…"):
        if ev.get("type") == "_end":
            raw = ev.get("raw") or ""
            continue
        yield ev
    data = extract_json(raw)
    ids = _save_characters_from_json(pid, data, replace=replace or n == 0)
    if not ids:
        yield {"type": "error", "message": "角色解析失败", "raw": (raw or "")[:1500]}
        return
    yield {"type": "status", "message": f"已保存 {len(ids)} 个角色"}
    yield {"type": "done", "count": len(ids)}


@router.post("/{pid}/wizard/settings")
async def wizard_settings(pid: int):
    project = _project(pid)

    async def gen():
        ctx = assemble(pid, "wizard_settings").for_template()
        ctx["style"] = project["style"] or "自由发挥"
        ctx["target"] = project["target_words"] or 200000
        messages = [
            {"role": "system", "content": prompts.WIZARD_SETTINGS_SYSTEM},
            {"role": "user", "content": prompts.WIZARD_SETTINGS_USER.format(**ctx)},
        ]
        raw = ""
        async for ev in _stream_wizard_llm(messages, status_msg="正在架构世界观…"):
            if ev.get("type") == "_end":
                raw = ev.get("raw") or ""
                continue
            yield ev
        data = extract_json(raw)
        if not data or not isinstance(data.get("sections"), list):
            yield {"type": "error", "message": "设定解析失败", "raw": (raw or "")[:1500]}
            return
        yield {"type": "status", "message": "正在保存世界观设定…"}
        db.execute(
            "INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET sections=excluded.sections, updated_at=excluded.updated_at",
            (pid, json.dumps(data["sections"], ensure_ascii=False), db.now()),
        )
        db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
        yield {"type": "done", "sections": data["sections"]}

    return sse(gen())


@router.post("/{pid}/wizard/characters")
async def wizard_characters(pid: int):
    async def gen():
        async for ev in _stream_generate_characters(pid, replace=True):
            yield ev

    return sse(gen())


@router.post("/{pid}/characters/generate")
async def generate_characters(pid: int, body: dict | None = None):
    """无角色时自动生成；已有角色时需传 replace=true 才覆盖重建。"""
    replace = bool((body or {}).get("replace"))

    async def gen():
        async for ev in _stream_generate_characters(pid, replace=replace):
            yield ev

    return sse(gen())


@router.post("/{pid}/wizard/outline")
async def wizard_outline(pid: int):
    project = _project(pid)

    async def gen():
        target = project["target_words"] or 200000
        chapter_count = max(6, round(target / 2500))
        ctx = assemble(pid, "wizard_outline").for_template()
        ctx["target"] = target
        ctx["chapter_count"] = chapter_count
        messages = [
            {"role": "system", "content": prompts.WIZARD_OUTLINE_SYSTEM},
            {"role": "user", "content": prompts.WIZARD_OUTLINE_USER.format(**ctx)},
        ]
        raw = ""
        async for ev in _stream_wizard_llm(messages, status_msg="正在规划全书大纲…"):
            if ev.get("type") == "_end":
                raw = ev.get("raw") or ""
                continue
            yield ev
        data = extract_json(raw)
        vols = (data or {}).get("volumes") if isinstance(data, dict) else None
        if not vols or not isinstance(vols, list):
            yield {"type": "error", "message": "大纲解析失败", "raw": (raw or "")[:1500]}
            return
        yield {"type": "status", "message": "正在写入卷章结构…"}
        old_chs = db.query("SELECT id FROM chapters WHERE project_id=?", (pid,))
        for ch in old_chs:
            db.execute("DELETE FROM chapter_versions WHERE chapter_id=?", (ch["id"],))
            db.execute("DELETE FROM reviews WHERE chapter_id=?", (ch["id"],))
        db.execute("DELETE FROM chapters WHERE project_id=?", (pid,))
        db.execute("DELETE FROM volumes WHERE project_id=?", (pid,))
        n_vols = n_chs = 0
        for vi, v in enumerate(vols):
            vid = db.execute(
                "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
                (pid, vi, str(v.get("title", f"第{vi+1}卷")), str(v.get("summary", ""))),
            )
            n_vols += 1
            for ci, c in enumerate(v.get("chapters") or []):
                if not isinstance(c, dict) or not c.get("title"):
                    continue
                db.execute(
                    "INSERT INTO chapters(project_id, volume_id, idx, title, brief, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (pid, vid, ci, str(c["title"]), str(c.get("brief", "")), db.now(), db.now()),
                )
                n_chs += 1
        db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
        yield {"type": "done", "volumes": n_vols, "chapters": n_chs}

    return sse(gen())
