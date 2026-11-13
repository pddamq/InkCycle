"""开书访谈：盘问式收集创作意图 → 汇编结构化创作蓝图。

这是"创建作品之前"的环节，因此不挂在 /api/projects 下。
"""
import json

from fastapi import APIRouter

from .. import prompts
from ..agent import extract_json, _run_with_tools
from ..context_usage import estimate_interview
from ..conversation_summarize import compress_history, format_history_for_prompt
from ..interview_tools import collect_interview_tools
from ..llm import LLMError
from .agent_api import sse, _render_history

router = APIRouter(prefix="/api/interview", tags=["interview"])

INTERVIEW_KEEP = 10
INTERVIEW_THRESHOLD = 8000


def _fallback_interview(raw: str) -> dict:
    return {
        "type": "interview",
        "phase": "asking",
        "intro": "",
        "questions": [
            {"key": "freeform", "label": "你的想法",
             "text": "先整体讲讲你想写一个什么样的故事？（题材、主角、核心冲突都可以一起说）"}
        ],
        "covered": [],
        "missing": [],
        "raw": (raw or "")[:500],
    }


async def _stream_llm(messages, *, status_msg: str, parse_kind: str):
    """通用：流式 LLM + 工具，产出 reasoning/tool/output 轨迹，最后解析 JSON。"""
    tools, handlers = collect_interview_tools()
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
            yield _fallback_interview(raw)
        else:
            yield {
                "type": "interview",
                "phase": data.get("phase", "asking"),
                "intro": data.get("intro", ""),
                "questions": data.get("questions") or [],
                "covered": data.get("covered") or [],
                "missing": data.get("missing") or [],
            }
    else:
        brief = extract_json(raw)
        if not isinstance(brief, dict):
            yield {"type": "compile", "ok": False, "error": "蓝图解析失败", "raw": (raw or "")[:800]}
            return
        try:
            target_words = int(brief.get("target_words") or 200000)
        except (TypeError, ValueError):
            target_words = 200000
        try:
            chapter_words = int(brief.get("chapter_words") or 2500)
        except (TypeError, ValueError):
            chapter_words = 2500
        yield {
            "type": "compile",
            "ok": True,
            "brief": brief,
            "project": {
                "title": brief.get("title") or "未命名作品",
                "genre": brief.get("genre") or "",
                "premise": brief.get("logline") or "",
                "style": brief.get("style") or "",
                "target_words": target_words,
                "brief": json.dumps(brief, ensure_ascii=False),
                "chapter_words": chapter_words,
            },
        }
    yield {"type": "done"}


async def _prepare_interview_history(body: dict) -> tuple[str, dict | None]:
    history = body.get("history") or []
    notes = body.get("history_notes") or ""
    through = int(body.get("history_through_index") or 0)
    recent, summary, new_through, did = await compress_history(
        history,
        kind="interview",
        existing_summary=notes,
        through_index=through,
        keep_recent=INTERVIEW_KEEP,
        threshold=INTERVIEW_THRESHOLD,
    )
    meta = None
    if did:
        meta = {"notes": summary, "through_index": new_through}
    hist_text = format_history_for_prompt(summary, recent)
    return hist_text, meta


@router.post("/next")
async def interview_next(body: dict):
    """SSE：根据访谈记录，返回下一轮要问的问题（或判定信息已足够）。"""
    body = body or {}
    hist_text, meta = await _prepare_interview_history(body)

    async def gen():
        if meta:
            yield {"type": "history_notes", **meta}
            yield {"type": "status", "message": "较早访谈已压缩为纪要"}
        notes = body.get("history_notes") or ""
        through = int(body.get("history_through_index") or 0)
        if meta:
            notes = meta.get("notes", notes)
            through = int(meta.get("through_index", through))
        yield {"type": "context_usage", **estimate_interview(
            body.get("history") or [], notes, through,
        )}
        messages = [
            {"role": "system", "content": prompts.INTERVIEW_SYSTEM},
            {"role": "user", "content": prompts.INTERVIEW_USER.format(history=hist_text)},
        ]
        async for ev in _stream_llm(messages, status_msg="编辑思考中…", parse_kind="next"):
            yield ev

    return sse(gen())


@router.post("/compile")
async def interview_compile(body: dict):
    """SSE：把整段访谈汇编成结构化创作蓝图。"""
    body = body or {}
    hist_text, meta = await _prepare_interview_history(body)

    async def gen():
        if meta:
            yield {"type": "history_notes", **meta}
        notes = body.get("history_notes") or ""
        through = int(body.get("history_through_index") or 0)
        if meta:
            notes = meta.get("notes", notes)
            through = int(meta.get("through_index", through))
        yield {"type": "context_usage", **estimate_interview(
            body.get("history") or [], notes, through, compile_mode=True,
        )}
        messages = [
            {"role": "system", "content": prompts.BRIEF_SYSTEM},
            {"role": "user", "content": prompts.BRIEF_USER.format(history=hist_text)},
        ]
        async for ev in _stream_llm(messages, status_msg="正在汇编创作蓝图…", parse_kind="compile"):
            yield ev

    return sse(gen())
