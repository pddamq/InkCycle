"""角色设计访谈：对话式收集人物意图 → 生成角色卡。"""
import json

from fastapi import APIRouter, HTTPException

from .. import db, prompts
from ..agent import extract_json, _run_with_tools
from ..character_interview_tools import collect_character_interview_tools
from ..llm import LLMError
from ..context_usage import estimate_character_interview
from ..conversation_summarize import (
    compress_history, format_history_for_prompt,
    get_char_design_summary_meta, save_char_design_summary_meta,
)
from ..project_context import assemble, save_char_design_notes, render_history as _render_history
from .agent_api import sse, _project, _save_characters_from_json

router = APIRouter(prefix="/api/projects", tags=["character-interview"])


def _project_context(pid: int, feature: str = "character_interview") -> dict:
    project = _project(pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    return assemble(pid, feature).for_template()


def _fallback_character_interview(raw: str) -> dict:
    return {
        "type": "character_interview",
        "phase": "asking",
        "intro": "",
        "questions": [{
            "key": "cast_overview",
            "label": "角色阵容",
            "text": "先说说你希望这本书有哪些核心角色？（主角、对手、感情线、重要配角各什么样）",
        }],
        "covered": [],
        "missing": [],
        "raw": (raw or "")[:500],
    }


async def _stream_character_llm(messages, *, status_msg: str, parse_kind: str):
    tools, handlers = collect_character_interview_tools()
    yield {"type": "status", "message": status_msg}
    holder = {}
    try:
        async for ev in _run_with_tools(messages, tools, handlers, holder, emit_deltas=False):
            if ev.get("type") == "output":
                continue
            yield ev
    except LLMError as e:
        yield {"type": "error", "message": str(e)}
        return

    raw = holder.get("text", "")
    if parse_kind == "next":
        data = extract_json(raw)
        if not isinstance(data, dict):
            yield _fallback_character_interview(raw)
        else:
            yield {
                "type": "character_interview",
                "phase": data.get("phase", "asking"),
                "intro": data.get("intro", ""),
                "questions": data.get("questions") or [],
                "covered": data.get("covered") or [],
                "missing": data.get("missing") or [],
            }
    else:
        data = extract_json(raw)
        if not isinstance(data, list) or not data:
            yield {"type": "characters", "ok": False, "error": "角色解析失败", "raw": (raw or "")[:800]}
            return
        normalized = []
        for c in data:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            normalized.append({
                "name": str(c["name"]),
                "role": str(c.get("role", "")),
                "profile": {k: v for k, v in c.items() if k not in ("name", "role") and v},
            })
        if not normalized:
            yield {"type": "characters", "ok": False, "error": "未解析到有效角色", "raw": (raw or "")[:800]}
            return
        yield {"type": "characters", "ok": True, "characters": normalized}
    yield {"type": "done"}


async def _prepare_char_history(pid: int, body: dict) -> tuple[str, dict | None]:
    history = body.get("history") or []
    notes, through = get_char_design_summary_meta(pid)
    recent, summary, new_through, did = await compress_history(
        history,
        kind="character",
        existing_summary=notes,
        through_index=through,
        keep_recent=10,
        threshold=8000,
    )
    meta = None
    if did:
        save_char_design_summary_meta(pid, summary, new_through)
        meta = {"notes": summary, "through_index": new_through}
    return format_history_for_prompt(summary, recent), meta


@router.post("/{pid}/characters/interview/next")
async def character_interview_next(pid: int, body: dict):
    body = body or {}
    ctx = _project_context(pid)
    hist_text, meta = await _prepare_char_history(pid, body)

    async def gen():
        if meta:
            yield {"type": "history_notes", **meta}
            yield {"type": "status", "message": "较早对话已压缩为纪要"}
        yield {"type": "context_usage", **estimate_character_interview(pid, body.get("history") or [])}
        messages = [
            {"role": "system", "content": prompts.CHARACTER_INTERVIEW_SYSTEM},
            {"role": "user", "content": prompts.CHARACTER_INTERVIEW_USER.format(
                history=hist_text, **ctx)},
        ]
        async for ev in _stream_character_llm(messages, status_msg="角色设计师思考中…", parse_kind="next"):
            yield ev

    return sse(gen())


@router.post("/{pid}/characters/interview/compile")
async def character_interview_compile(pid: int, body: dict):
    body = body or {}
    ctx = _project_context(pid, "character_compile")
    hist_text, meta = await _prepare_char_history(pid, body)

    async def gen():
        if meta:
            yield {"type": "history_notes", **meta}
        yield {"type": "context_usage", **estimate_character_interview(
            pid, body.get("history") or [], compile_mode=True,
        )}
        messages = [
            {"role": "system", "content": prompts.CHARACTER_COMPILE_SYSTEM},
            {"role": "user", "content": prompts.CHARACTER_COMPILE_USER.format(
                history=hist_text, **ctx)},
        ]
        async for ev in _stream_character_llm(messages, status_msg="正在生成角色卡…", parse_kind="compile"):
            yield ev

    return sse(gen())


@router.post("/{pid}/characters/interview/save")
def character_interview_save(pid: int, body: dict):
    _project_context(pid)  # 404 if missing
    chars = body.get("characters")
    if not isinstance(chars, list) or not chars:
        raise HTTPException(400, "characters 不能为空")
    replace = bool(body.get("replace", True))
    payload = []
    for c in chars:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        profile = c.get("profile") if isinstance(c.get("profile"), dict) else {}
        for k, v in c.items():
            if k not in ("name", "role", "profile", "id") and v:
                profile[k] = v
        payload.append({
            "name": str(c["name"]),
            "role": str(c.get("role", "")),
            **profile,
        })
    ids = _save_characters_from_json(pid, payload, replace=replace)
    if not ids:
        raise HTTPException(400, "保存失败")
    history = body.get("history") or []
    if history:
        save_char_design_notes(pid, history)
    return {"ok": True, "count": len(ids)}
