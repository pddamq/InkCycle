"""估算 AI 对话上下文占用（Cursor 式 breakdown）。"""
from __future__ import annotations

import json
from typing import Any

from . import db, prompts
from .agent import _cap, _chapter, _chat_context, _current_content, _format_references, _project
from .character_interview_tools import collect_character_interview_tools
from .conversation_summarize import (
    DEFAULT_KEEP_RECENT,
    INTERVIEW_KEEP_RECENT,
    get_char_design_summary_meta,
    get_chat_summary_meta,
    format_history_for_prompt,
)
from .interview_tools import collect_interview_tools
from .project_context import assemble, render_history
from .skills import build_skills_block
from .tools import collect_tools

DEFAULT_CONTEXT_WINDOW = 128000

CATEGORIES: list[tuple[str, str, str]] = [
    ("system", "系统提示", "#9aa0a6"),
    ("tools", "工具定义", "#8b5cf6"),
    ("skills", "技能库", "#22c55e"),
    ("book_context", "本书上下文", "#f59e0b"),
    ("chapter_content", "章节正文", "#06b6d4"),
    ("references", "引用/选中", "#ec4899"),
    ("summarized", "对话纪要", "#ef4444"),
    ("conversation", "对话原文", "#64748b"),
]


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    # 中文为主：约 1.8 字符 / token
    return max(1, int(len(str(text)) / 1.8))


def estimate_tools_tokens(tools: list | None) -> int:
    if not tools:
        return 0
    return estimate_tokens(json.dumps(tools, ensure_ascii=False))


def get_context_limit() -> int:
    cfg = db.get_config()
    return db.cfg_int(cfg, "context_window", DEFAULT_CONTEXT_WINDOW)


def split_conversation(
    history: list,
    *,
    notes: str = "",
    through: int = 0,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> tuple[str, list]:
    """同步拆分：已压缩纪要 + 最近原文（不触发 LLM）。"""
    if not history:
        return notes or "", []
    through = max(0, int(through or 0))
    if notes and through > 0:
        return notes, list(history[through:])
    if len(history) <= keep_recent:
        # through 缺失时忽略孤儿纪要，避免与全文重复计数
        if notes and not through:
            return "", list(history)
        return notes or "", list(history)
    if notes:
        start = through if through > 0 else len(history) - keep_recent
        return notes, list(history[start:])
    return "", list(history)


def build_usage(breakdown: dict[str, int], *, limit: int | None = None) -> dict[str, Any]:
    limit = limit or get_context_limit()
    items: list[dict] = []
    total = 0
    seen = set()
    for key, label, color in CATEGORIES:
        tokens = int(breakdown.get(key) or 0)
        if tokens <= 0:
            continue
        items.append({"key": key, "label": label, "tokens": tokens, "color": color})
        total += tokens
        seen.add(key)
    for key, val in breakdown.items():
        if key in seen or key.startswith("_"):
            continue
        tokens = int(val or 0)
        if tokens <= 0:
            continue
        items.append({"key": key, "label": key, "tokens": tokens, "color": "#94a3b8"})
        total += tokens
    pct = min(100, round(total / limit * 100)) if limit else 0
    return {
        "total": total,
        "limit": limit,
        "percent": pct,
        "remaining": max(0, limit - total),
        "items": sorted(items, key=lambda x: -x["tokens"]),
    }


def usage_event(breakdown: dict[str, int], *, limit: int | None = None) -> dict[str, Any]:
    payload = build_usage(breakdown, limit=limit)
    return {"type": "context_usage", **payload}


def usage_from_messages(messages: list, tools: list | None = None) -> dict[str, Any]:
    """从已组装的 messages 粗估（system + 对话 + 工具）。"""
    system = conversation = 0
    for m in messages or []:
        role = m.get("role")
        text = m.get("content") or ""
        if role == "system":
            system += estimate_tokens(text)
        elif role in ("user", "assistant"):
            conversation += estimate_tokens(text)
    return build_usage({
        "system": system,
        "tools": estimate_tools_tokens(tools),
        "conversation": conversation,
    })


def _chat_template_system_tokens() -> int:
    """CHAT_SYSTEM 固定模板（占位符不计入）。"""
    tpl = prompts.CHAT_SYSTEM
    for key in ("context", "current_content", "words", "skills_block"):
        tpl = tpl.replace("{" + key + "}", "")
    return estimate_tokens(tpl)


async def estimate_chat(
    project_id: int,
    chapter_id: int,
    history: list | None = None,
    references=None,
    selection=None,
    *,
    summary: str | None = None,
    recent: list | None = None,
) -> dict[str, Any]:
    chapter = _chapter(chapter_id)
    project = _project(project_id)
    if not chapter or not project:
        return build_usage({})

    context, _words = _chat_context(project_id, chapter_id, project, chapter)
    current = _cap(_current_content(chapter) or "（空）", 8000)
    skills = build_skills_block("draft")
    ref_block = _format_references(references, selection)

    if summary is None or recent is None:
        notes, through = get_chat_summary_meta(project_id, chapter_id)
        summary, recent = split_conversation(history or [], notes=notes, through=through)
    else:
        recent = list(recent or [])
        summary = summary or ""

    tools, _ = collect_tools(project_id, chapter_id, write=True, chat=True, holder={})

    return build_usage({
        "system": _chat_template_system_tokens(),
        "book_context": estimate_tokens(context),
        "chapter_content": estimate_tokens(current),
        "skills": estimate_tokens(skills),
        "references": estimate_tokens(ref_block),
        "summarized": estimate_tokens(summary) if summary else 0,
        "conversation": estimate_tokens(render_history(recent)),
        "tools": estimate_tools_tokens(tools),
    })


def estimate_interview(
    history: list | None = None,
    history_notes: str = "",
    history_through_index: int = 0,
    *,
    compile_mode: bool = False,
) -> dict[str, Any]:
    summary, recent = split_conversation(
        history or [],
        notes=history_notes or "",
        through=history_through_index,
        keep_recent=INTERVIEW_KEEP_RECENT,
    )
    hist_text = format_history_for_prompt(summary, recent)
    tools, _ = collect_interview_tools()

    user_wrapper = (prompts.BRIEF_USER if compile_mode else prompts.INTERVIEW_USER).replace("{history}", "")
    system = prompts.BRIEF_SYSTEM if compile_mode else prompts.INTERVIEW_SYSTEM

    return build_usage({
        "system": estimate_tokens(system) + estimate_tokens(user_wrapper),
        "summarized": estimate_tokens(summary),
        "conversation": estimate_tokens(render_history(recent)),
        "tools": estimate_tools_tokens(tools),
    })


def estimate_character_interview(
    project_id: int,
    history: list | None = None,
    *,
    compile_mode: bool = False,
) -> dict[str, Any]:
    project = _project(project_id)
    if not project:
        return build_usage({})

    notes, through = get_char_design_summary_meta(project_id)
    summary, recent = split_conversation(
        history or [],
        notes=notes or "",
        through=through,
        keep_recent=INTERVIEW_KEEP_RECENT,
    )
    hist_text = format_history_for_prompt(summary, recent)
    ctx = assemble(project_id, "character_interview").for_template()
    tools, _ = collect_character_interview_tools()

    ctx_payload = {
        "title": project.get("title") or "",
        "genre": project.get("genre") or "",
        "premise": project.get("premise") or "",
        "brief_block": ctx.get("brief_block") or "",
        "creation_notes": ctx.get("creation_notes") or "",
        "char_design_notes": ctx.get("char_design_notes") or "",
        "world": ctx.get("world") or "",
        "existing_chars": ctx.get("existing_chars") or ctx.get("characters") or "",
        "outline_snippet": ctx.get("outline_compact") or ctx.get("outline_snippet") or "",
        "history": "",
        **ctx,
    }

    if compile_mode:
        system = prompts.CHARACTER_COMPILE_SYSTEM
        book_block = prompts.CHARACTER_COMPILE_USER.format(history="", **ctx_payload)
    else:
        system = prompts.CHARACTER_INTERVIEW_SYSTEM
        book_block = prompts.CHARACTER_INTERVIEW_USER.format(**ctx_payload)

    return build_usage({
        "system": estimate_tokens(system),
        "book_context": estimate_tokens(book_block),
        "summarized": estimate_tokens(summary),
        "conversation": estimate_tokens(render_history(recent)),
        "tools": estimate_tools_tokens(tools),
    })


async def build_chat_usage_event(
    project_id: int,
    chapter_id: int,
    history: list | None,
    references=None,
    selection=None,
    *,
    summary: str | None = None,
    recent: list | None = None,
) -> dict[str, Any]:
    usage = await estimate_chat(
        project_id, chapter_id, history, references, selection,
        summary=summary, recent=recent,
    )
    return {"type": "context_usage", **usage}
