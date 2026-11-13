"""对话历史压缩（Cursor 式 summarize）：超预算时将较早轮次 LLM 压成纪要，保留最近原文。"""
from __future__ import annotations

from . import prompts
from .llm import LLMError, chat
from .project_context import cap, merge_brief_meta, render_history

# 默认：超过阈值则压缩；保留最近 N 条消息（user/assistant 各算一条）
DEFAULT_KEEP_RECENT = 8
DEFAULT_THRESHOLD = 5000
INTERVIEW_KEEP_RECENT = 10
INTERVIEW_THRESHOLD = 8000


def format_history_for_prompt(summary: str, recent: list) -> str:
    parts = []
    if summary and summary.strip():
        parts.append("【此前对话纪要（更早轮次已压缩）】\n" + summary.strip())
    recent_text = render_history(recent)
    if recent_text and recent_text != "（尚无记录）":
        parts.append("【最近对话原文】\n" + recent_text)
    return "\n\n".join(parts) if parts else "（尚无记录）"


async def _summarize_text(text: str, kind: str) -> str:
    templates = {
        "chat": (prompts.CHAT_HISTORY_SUMMARY_SYSTEM, prompts.CHAT_HISTORY_SUMMARY_USER),
        "interview": (prompts.INTERVIEW_HISTORY_SUMMARY_SYSTEM, prompts.INTERVIEW_HISTORY_SUMMARY_USER),
        "character": (prompts.CHARACTER_HISTORY_SUMMARY_SYSTEM, prompts.CHARACTER_HISTORY_SUMMARY_USER),
    }
    system, user_tpl = templates[kind]
    out = await chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user_tpl.format(text=cap(text, 12000))},
    ])
    return cap((out or "").strip(), 6000)


async def _merge_summaries(existing: str, new_chunk: str, kind: str) -> str:
    out = await chat([
        {"role": "system", "content": prompts.CONVERSATION_SUMMARY_MERGE_SYSTEM},
        {"role": "user", "content": prompts.CONVERSATION_SUMMARY_MERGE_USER.format(
            kind=kind,
            existing=cap(existing, 5000),
            new_chunk=cap(new_chunk, 8000),
        )},
    ])
    return cap((out or "").strip(), 6000)


async def compress_history(
    history: list,
    *,
    kind: str = "chat",
    existing_summary: str = "",
    through_index: int = 0,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[list, str, int, bool]:
    """返回 (recent_messages, summary, new_through_index, did_compress)。"""
    if not history:
        return [], existing_summary or "", 0, False

    through_index = max(0, int(through_index or 0))
    cut = len(history) - keep_recent if len(history) > keep_recent else 0
    rendered_all = render_history(history)

    if cut == 0:
        return list(history), existing_summary or "", through_index, False

    recent = list(history[-keep_recent:])

    # 已压缩过且没有新增长需要折叠
    if existing_summary and through_index >= cut:
        return recent, existing_summary, through_index, False

    # 未超预算：保留已有纪要 + 未压缩部分的原文
    if len(rendered_all) <= threshold:
        if existing_summary and through_index > 0:
            return list(history[through_index:]), existing_summary, through_index, False
        return list(history), existing_summary or "", through_index, False

    start = max(through_index, 0)
    if start >= cut and existing_summary:
        return recent, existing_summary, cut, False

    chunk = history[start:cut]
    chunk_text = render_history(chunk)
    if not chunk_text.strip():
        return recent, existing_summary or "", cut, bool(existing_summary)

    try:
        if existing_summary:
            summary = await _merge_summaries(existing_summary, chunk_text, kind)
        else:
            summary = await _summarize_text(render_history(history[:cut]), kind)
    except LLMError:
        summary = cap(render_history(history[:cut]), 4000)

    return recent, summary, cut, True


# ---------------------------------------------------------------- 持久化（按书 / 按章）

def _brief_dict(project_id: int) -> dict:
    from . import db
    row = db.query_one("SELECT brief FROM projects WHERE id=?", (project_id,))
    brief = db.jload(row["brief"] if row else "{}", {}) or {}
    return brief if isinstance(brief, dict) else {}


def get_chat_summary_meta(project_id: int, chapter_id: int) -> tuple[str, int]:
    cs = _brief_dict(project_id).get("chat_summaries") or {}
    entry = cs.get(str(chapter_id)) or {}
    return (entry.get("summary") or "", int(entry.get("through_index") or 0))


def save_chat_summary_meta(project_id: int, chapter_id: int, summary: str, through_index: int) -> None:
    brief = _brief_dict(project_id)
    cs = dict(brief.get("chat_summaries") or {})
    cs[str(chapter_id)] = {"summary": summary, "through_index": through_index}
    merge_brief_meta(project_id, {"chat_summaries": cs})


def get_char_design_summary_meta(project_id: int) -> tuple[str, int]:
    entry = _brief_dict(project_id).get("char_design_summarize") or {}
    return (entry.get("summary") or "", int(entry.get("through_index") or 0))


def save_char_design_summary_meta(project_id: int, summary: str, through_index: int) -> None:
    merge_brief_meta(project_id, {
        "char_design_summarize": {"summary": summary, "through_index": through_index},
    })
