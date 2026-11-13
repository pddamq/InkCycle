"""Agent 核心：上下文构建 + 起草/审校/修订/自动循环（SSE 事件流）。

事件协议（JSON per SSE data:）：
  status         阶段开始/进展
  delta          正文增量（写作进编辑器）
  output         非正文输出流（审校 JSON 等，仅轨迹面板）
  reasoning      思考/推理增量
  tool_call_delta 工具调用参数流式片段
  tool_call      模型请求调用工具
  tool_result    工具执行结果
  review         审校报告（score/issues/summary）
  version_saved  版本已保存
  phase          自动循环的阶段切换
  done           结束（final_score/rounds）
  error          错误
"""
import inspect
import json
import re

from . import db, prompts
from .llm import stream_chat, chat, LLMError
from .project_context import assemble, style_block as _shared_style_block
from .prompts import IMITATE_WRITING_GUIDE
from .conversation_summarize import (
    compress_history, format_history_for_prompt,
    get_chat_summary_meta, save_chat_summary_meta,
)
from .skills import build_skills_block
from .tools import collect_tools

MAX_TOOL_ROUNDS = 4
WORD_RE = re.compile(r"\s")


def count_words(text: str) -> int:
    return len(WORD_RE.sub("", text or ""))


def _cap(text, limit, tail=False):
    if not text or len(text) <= limit:
        return text or ""
    clipped = text[-limit:] if tail else text[:limit]
    return clipped + f"…（已截断，原文{len(text)}字）"


# ---------------------------------------------------------------- 上下文构建

def _project(pid):
    return db.query_one("SELECT * FROM projects WHERE id=?", (pid,))


def _world_text(pid, cap=3000):
    row = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    sections = db.jload(row["sections"], []) if row else []
    parts = [f"■ {s.get('title','')}\n{s.get('content','')}" for s in sections if s.get("title") or s.get("content")]
    return _cap("\n\n".join(parts), cap) or "（暂无设定）"


def _world_compact(pid, cap=1500):
    row = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    sections = db.jload(row["sections"], []) if row else []
    parts = [f"{s.get('title','')}：{_cap(s.get('content',''), 200)}" for s in sections]
    return _cap("；".join(p for p in parts if p), cap) or "（暂无设定）"


def _characters_text(pid, cap_each=600):
    rows = db.query("SELECT * FROM characters WHERE project_id=? ORDER BY id", (pid,))
    if not rows:
        return "（暂无人物）"
    blocks = []
    for r in rows:
        profile = db.jload(r["profile"], {})
        lines = [f"{r['name']}（{r['role']}）"]
        for k, v in profile.items():
            if v:
                lines.append(f"  · {k}：{_cap(str(v), 160)}")
        blocks.append(_cap("\n".join(lines), cap_each))
    return "\n".join(blocks)


def _characters_compact(pid):
    rows = db.query("SELECT * FROM characters WHERE project_id=? ORDER BY id", (pid,))
    if not rows:
        return "（暂无人物）"
    out = []
    for r in rows:
        profile = db.jload(r["profile"], {})
        brief = profile.get("personality") or profile.get("goal") or ""
        out.append(f"{r['name']}（{r['role']}）：{_cap(str(brief), 80)}")
    return "\n".join(out)


def _prev_text(chapter, cap=1600):
    """前文脉络：前 3 章摘要 + 上一章结尾片段。"""
    rows = db.query(
        "SELECT id, title, summary, volume_id, idx FROM chapters "
        "WHERE project_id=? AND id!=? AND summary!='' "
        "ORDER BY volume_id DESC, idx DESC LIMIT 3",
        (chapter["project_id"], chapter["id"]),
    )
    summaries = [f"- {r['title']}：{r['summary']}" for r in reversed(rows)]
    parts = ["\n".join(summaries) if summaries else "（本书开篇，无前文）"]
    prev_ch = db.query_one(
        "SELECT id, title, current_version_id FROM chapters "
        "WHERE project_id=? AND id!=? AND current_version_id IS NOT NULL "
        "ORDER BY volume_id DESC, idx DESC LIMIT 1",
        (chapter["project_id"], chapter["id"]),
    )
    if prev_ch:
        ver = db.query_one(
            "SELECT content FROM chapter_versions WHERE id=?", (prev_ch["current_version_id"],)
        )
        if ver and ver["content"]:
            parts.append(f"【上一章结尾】\n{_cap(ver['content'], 400, tail=True)}")
    return _cap("\n\n".join(parts), cap)


def _foreshadow_text(pid, chapter_id):
    rows = db.query(
        "SELECT f.*, c.title AS planted_title FROM foreshadowing f "
        "LEFT JOIN chapters c ON c.id=f.planted_chapter_id "
        "WHERE f.project_id=? AND f.status='open' ORDER BY f.id",
        (pid,),
    )
    if not rows:
        return "（暂无待处理伏笔，可为本章自然埋设新伏笔，创作时留意登记）"
    out = []
    for r in rows:
        mine = "（本章可埋设/推进）" if not r["planted_chapter_id"] else f"（已埋于《{r['planted_title']}》）"
        out.append(f"- {r['description']}{mine}")
    return "\n".join(out)


def _timeline_text(pid, cap=1200):
    rows = db.query(
        "SELECT t.*, c.title AS chapter_title FROM timeline_events t "
        "LEFT JOIN chapters c ON c.id=t.chapter_id "
        "WHERE t.project_id=? ORDER BY t.idx DESC, t.id DESC LIMIT 8",
        (pid,),
    )
    if not rows:
        return "（时间线暂无事件）"
    lines = [f"- {r['time_label']}：{r['description']}（《{r['chapter_title'] or '未关联'}》）"
             for r in reversed(rows)]
    return _cap("\n".join(lines), cap)


def _current_content(chapter):
    if not chapter.get("current_version_id"):
        return ""
    ver = db.query_one(
        "SELECT content FROM chapter_versions WHERE id=?", (chapter["current_version_id"],)
    )
    return ver["content"] if ver else ""


def _chapter(chapter_id):
    return db.query_one("SELECT * FROM chapters WHERE id=?", (chapter_id,))


def _style_block(project) -> str:
    brief = db.jload(project.get("brief"), {}) or {}
    if not isinstance(brief, dict):
        return ""
    profile = brief.get("style_profile")
    lines = []
    if isinstance(profile, dict) and profile:
        labels = (
            ("style_summary", "总述"), ("pov", "视角"), ("pacing", "节奏"),
            ("tone", "基调"), ("sentence", "句式"), ("dialogue", "对话"),
            ("vocabulary", "用词"), ("rhetoric", "修辞"), ("avoid", "避AI腔"),
        )
        for k, lab in labels:
            if profile.get(k):
                lines.append(f"- {lab}：{profile[k]}")
    elif isinstance(profile, str) and profile.strip():
        lines.append(profile.strip())
    if not lines:
        return ""
    block = "【文风档案】\n" + "\n".join(lines)
    if brief.get("imitate") or brief.get("source") == "imitated":
        ref = brief.get("source_title") or brief.get("references") or "参考书"
        block += (
            f"\n【仿写纪律·摘要】参考书《{ref}》仅借鉴文风；"
            "必须写全新故事、全新人物、全新专有名词与全新句子；"
            "禁止复用人名、地名、势力、情节桥段、原文措辞；"
            "成文须低 AI 味，忌排比堆砌、空泛形容词与说明腔对话。"
        )
        block += IMITATE_WRITING_GUIDE
    return "\n" + block



# ---------------------------------------------------------------- 工具调用循环

async def _run_with_tools(messages, tools, handlers, holder, emit_deltas=True, max_tool_rounds=None,
                          *, final_text_only=False):
    """带工具调用的对话循环（异步生成器）。

    实时产出事件；结束后把完整正文写入 holder["text"]。
    emit_deltas=False 时仍累积正文但不外发 delta 事件（用于审校：避免把 JSON 当作正文流式写进编辑器）。
    final_text_only=True 时 holder 只保留最后一轮文本（审校 JSON 等结构化输出）。
    """
    text_parts = []
    rounds_limit = max_tool_rounds if max_tool_rounds is not None else MAX_TOOL_ROUNDS
    try:
        for _round in range(rounds_limit):
            round_parts = []
            calls = []
            async for ev in stream_chat(messages, tools=tools if tools else None):
                if ev["type"] == "text":
                    round_parts.append(ev["text"])
                    if emit_deltas:
                        yield {"type": "delta", "text": ev["text"]}
                    else:
                        yield {"type": "output", "text": ev["text"]}
                elif ev["type"] == "reasoning":
                    yield {"type": "reasoning", "text": ev["text"]}
                elif ev["type"] == "tool_call_delta":
                    yield ev
                elif ev["type"] == "tool_calls":
                    calls = ev["calls"]
            if final_text_only:
                text_parts = round_parts
            else:
                text_parts.extend(round_parts)
            if not calls:
                break
            assistant_msg = {
                "role": "assistant",
                "content": "".join(round_parts) or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                    for c in calls
                ],
            }
            messages.append(assistant_msg)
            for i, c in enumerate(calls):
                yield {"type": "tool_call", "index": i, "name": c["name"], "arguments": c["arguments"]}
                handler = handlers.get(c["name"])
                if handler is None:
                    result = f"未知工具：{c['name']}"
                else:
                    try:
                        if inspect.iscoroutinefunction(handler):
                            result = await handler(c["arguments"])
                        else:
                            result = handler(c["arguments"])
                    except Exception as e:
                        result = f"工具执行出错：{e}"
                result = str(result)[:8000]
                yield {"type": "tool_result", "name": c["name"], "result": result[:600]}
                if c["name"] == "update_chapter":
                    body = (c["arguments"].get("content") or "").strip()
                    if body:
                        yield {"type": "content_set", "text": body}
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
            if holder.get("ask_user"):
                break
    finally:
        holder["text"] = "".join(text_parts)


# ---------------------------------------------------------------- 版本与摘要

def _save_version(chapter_id, vtype, content, review_id=None, note="") -> dict:
    wid = count_words(content)
    vid = db.execute(
        "INSERT INTO chapter_versions(chapter_id, vtype, content, word_count, review_id, note, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (chapter_id, vtype, content, wid, review_id, note, db.now()),
    )
    status_map = {"draft": "drafted", "revise": "reviewed", "manual": "drafted", "restore": "final"}
    db.execute(
        "UPDATE chapters SET current_version_id=?, word_count=?, status=?, updated_at=? WHERE id=?",
        (vid, wid, status_map.get(vtype, "drafted"), db.now(), chapter_id),
    )
    return {"version_id": vid, "word_count": wid}


async def _auto_summary(chapter) -> "list":
    """生成章节摘要，返回需要继续外发的事件列表（失败静默）。"""
    cfg = db.get_config()
    if not db.cfg_bool(cfg, "auto_summary", True):
        return []
    try:
        content = _current_content(chapter) or ""
        summary = await chat([
            {"role": "system", "content": prompts.SUMMARY_SYSTEM},
            {"role": "user", "content": prompts.SUMMARY_USER.format(
                brief=_cap(chapter["brief"], 300), content=_cap(content, 3000))},
        ])
        if summary:
            db.execute("UPDATE chapters SET summary=? WHERE id=?", (summary[:300], chapter["id"]))
            return [{"type": "status", "message": "章节摘要已更新。"}]
    except LLMError:
        pass
    return []


# ---------------------------------------------------------------- 对话写作

def _chat_context(project_id, chapter_id, project, chapter) -> tuple[str, int]:
    volume = db.query_one("SELECT * FROM volumes WHERE id=?", (chapter["volume_id"],))
    cfg = db.get_config()
    words = db.cfg_int(cfg, "chapter_words", 2500)
    brief = db.jload(project.get("brief"), {})
    if isinstance(brief, dict) and brief.get("chapter_words"):
        try:
            words = int(brief["chapter_words"])
        except (TypeError, ValueError):
            pass
    ctx = assemble(project_id, "chat", chapter_id)
    review = db.query_one(
        "SELECT round, score, report FROM reviews WHERE chapter_id=? ORDER BY id DESC LIMIT 1",
        (chapter_id,),
    )
    parts = [
        f"书名：{project['title']}",
        f"类型：{project['genre'] or '未指定'}",
        f"风格基调：{project['style'] or '未指定'}",
        _shared_style_block(project).strip(),
        f"【创作蓝图】\n{ctx.get('brief_block')}",
        f"【开书访谈纪要】\n{ctx.get('creation_notes')}",
        f"卷：{volume['title'] if volume else '正文'}",
        f"章节标题：{chapter['title']}",
        f"本章梗概：{chapter['brief'] or '（无，请依据前文与设定发挥）'}",
        f"【世界观要点】\n{ctx.get('world')}",
        f"【人物要点】\n{ctx.get('characters_compact') or ctx.get('characters')}",
        f"【大纲摘要】\n{ctx.get('outline_compact')}",
        f"【前文脉络】\n{ctx.get('prev')}",
        f"【伏笔任务】\n{ctx.get('foreshadow')}",
    ]
    if review:
        rep = db.jload(review["report"], {})
        issues = rep.get("issues") or []
        parts.append(
            f"【最新审校·第{review['round']}轮 {review['score']}分】\n"
            f"{rep.get('summary', '')}\n"
            + "\n".join(
                f"- [{it.get('severity')}] {it.get('description', '')} → {it.get('suggestion', '')}"
                for it in issues[:8]
            )
        )
    return "\n\n".join(p for p in parts if p), words


def _format_references(references, selection) -> str:
    parts = []
    if selection and (selection.get("text") or "").strip():
        parts.append("【用户选中段落（优先处理范围）】\n" + _cap(selection["text"].strip(), 2000))
    if references:
        lines = []
        for ref in references[:12]:
            label = ref.get("label") or ref.get("type") or "引用"
            content = _cap((ref.get("content") or "").strip(), 800)
            lines.append(f"@{label}（{ref.get('type', '')}）\n{content}")
        if lines:
            parts.append("【用户 @ 引用上下文】\n" + "\n\n".join(lines))
    return "\n\n".join(parts)


def _save_review_from_report(chapter_id, chapter, report: dict) -> dict:
    issues = report.get("issues") or []
    score = int(report.get("score") or 0)
    round_no = db.query_one(
        "SELECT COUNT(*) AS n FROM reviews WHERE chapter_id=?", (chapter_id,)
    )["n"] + 1
    rid = db.execute(
        "INSERT INTO reviews(chapter_id, version_id, round, score, report, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (chapter_id, chapter["current_version_id"], round_no, score,
         json.dumps({"summary": report.get("summary", ""), "issues": issues}, ensure_ascii=False),
         db.now()),
    )
    return {"review_id": rid, "round": round_no, "score": score,
            "issues": issues, "summary": report.get("summary", "")}


async def run_chat(project_id, chapter_id, history: list, references=None, selection=None):
    """Cursor 式对话写作：多轮 messages + 工具 + 流式轨迹。"""
    chapter = _chapter(chapter_id)
    project = _project(project_id)
    if not chapter or not project:
        yield {"type": "error", "message": "章节或项目不存在"}
        return
    context, words = _chat_context(project_id, chapter_id, project, chapter)
    current = _current_content(chapter) or "（空）"
    system = prompts.CHAT_SYSTEM.format(
        context=context,
        current_content=_cap(current, 8000),
        words=words,
        skills_block=build_skills_block("draft"),
    )
    ref_block = _format_references(references, selection)
    if ref_block:
        system += "\n\n" + ref_block

    notes, through = get_chat_summary_meta(project_id, chapter_id)
    recent, summary, new_through, did_compress = await compress_history(
        history or [],
        kind="chat",
        existing_summary=notes,
        through_index=through,
    )
    if did_compress:
        save_chat_summary_meta(project_id, chapter_id, summary, new_through)
        yield {"type": "status", "message": f"较早对话已压缩为纪要（保留最近 {len(recent)} 条）"}
    elif summary:
        pass  # 沿用已存纪要
    if summary:
        system += "\n\n" + format_history_for_prompt(summary, [])

    messages = [{"role": "system", "content": system}]
    for turn in recent:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    from .context_usage import build_chat_usage_event
    yield await build_chat_usage_event(
        project_id, chapter_id, history,
        references=references, selection=selection,
        summary=summary, recent=recent,
    )

    holder = {}
    tools, handlers = collect_tools(project_id, chapter_id, write=True, chat=True, holder=holder)
    yield {"type": "status", "message": f"Agent 就绪（{len(tools)} 个工具可用）"}

    chapter_written = ""
    try:
        async for ev in _run_with_tools(messages, tools, handlers, holder, emit_deltas=True):
            if ev.get("type") == "content_set":
                chapter_written = ev.get("text") or chapter_written
            yield ev
    except LLMError as e:
        yield {"type": "error", "message": str(e)}
        return

    if holder.get("ask_user"):
        yield {"type": "ask_user", **holder["ask_user"]}
        yield {"type": "done", "stage": "chat", "pending_question": True}
        return

    raw = (holder.get("text") or "").strip()
    report = extract_json(raw) if raw else None

    if report and "score" in report:
        rev = _save_review_from_report(chapter_id, chapter, report)
        yield {"type": "review", **rev}
    elif chapter_written:
        saved = _save_version(chapter_id, "draft", chapter_written, note="Agent 对话写作")
        yield {"type": "version_saved", "vtype": "draft", **saved}
        for ev in await _auto_summary(_chapter(chapter_id)):
            yield ev
    elif raw and len(raw) > 200 and report is None:
        saved = _save_version(chapter_id, "draft", raw, note="Agent 对话写作")
        yield {"type": "version_saved", "vtype": "draft", **saved}
        for ev in await _auto_summary(_chapter(chapter_id)):
            yield ev
        yield {"type": "content_set", "text": raw}

    reply = raw
    if chapter_written and (not reply or reply == chapter_written or len(reply) > 400):
        reply = "正文已写入编辑器。"
    if reply and report is None and reply != chapter_written:
        yield {"type": "message", "text": reply[:2000]}
    elif chapter_written and not reply:
        yield {"type": "message", "text": "正文已写入编辑器。"}

    yield {"type": "done", "stage": "chat"}


# ---------------------------------------------------------------- 各阶段

async def run_draft(project_id, chapter_id, *, lite=False, skip_summary=False):
    chapter = _chapter(chapter_id)
    project = _project(project_id)
    if not chapter or not project:
        yield {"type": "error", "message": "章节或项目不存在"}
        return
    cfg = db.get_config()
    words = db.cfg_int(cfg, "chapter_words", 2500)
    brief = db.jload(project.get("brief"), {})
    if isinstance(brief, dict) and brief.get("chapter_words"):
        try:
            words = int(brief["chapter_words"])
        except (TypeError, ValueError):
            pass
    volume = db.query_one("SELECT * FROM volumes WHERE id=?", (chapter["volume_id"],))

    yield {"type": "status", "stage": "draft", "message": "正在构建写作上下文…"}
    ctx = assemble(project_id, "draft", chapter_id).for_template()
    system = prompts.DRAFT_SYSTEM.format(skills_block=build_skills_block("draft"))
    user = prompts.DRAFT_USER.format(
        words=words,
        title=project["title"],
        genre=project["genre"] or "未指定",
        style=project["style"] or "未指定",
        style_block=ctx.get("style_block") or _style_block(project),
        brief_block=ctx.get("brief_block"),
        creation_notes=ctx.get("creation_notes"),
        world=ctx.get("world"),
        characters=ctx.get("characters"),
        outline_snippet=ctx.get("outline_snippet"),
        volume=volume["title"] if volume else "正文",
        chapter_title=chapter["title"],
        brief=chapter["brief"] or "（无梗概，请依据前文与卷概要自由发挥）",
        prev=ctx.get("prev"),
        foreshadow=ctx.get("foreshadow"),
        timeline=ctx.get("timeline"),
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    tools, handlers = collect_tools(project_id, chapter_id, write=not lite, lite=lite)
    tool_rounds = 1 if lite else MAX_TOOL_ROUNDS
    yield {"type": "status", "stage": "draft", "message": f"开始生成初稿（可用工具 {len(tools)} 个）…"}

    holder = {}
    try:
        async for ev in _run_with_tools(messages, tools, handlers, holder, max_tool_rounds=tool_rounds):
            yield ev
    except LLMError as e:
        yield {"type": "error", "message": str(e)}
        return
    text = holder.get("text", "")
    if not text.strip():
        yield {"type": "error", "message": "模型未返回正文"}
        return
    saved = _save_version(chapter_id, "draft", text, note="Agent 初稿")
    yield {"type": "version_saved", "vtype": "draft", **saved}
    if not skip_summary:
        for ev in await _auto_summary(_chapter(chapter_id)):
            yield ev
    yield {"type": "done", "stage": "draft", **saved}


async def run_review(project_id, chapter_id):
    chapter = _chapter(chapter_id)
    if not chapter:
        yield {"type": "error", "message": "章节不存在"}
        return
    content = _current_content(chapter)
    if not content:
        yield {"type": "error", "message": "本章还没有正文，请先生成或撰写初稿"}
        return
    yield {"type": "status", "stage": "review", "message": "正在构建审校上下文…"}
    ctx = assemble(project_id, "review", chapter_id).for_template()
    messages = [
        {"role": "system", "content": prompts.REVIEW_SYSTEM},
        {"role": "user", "content": prompts.REVIEW_USER.format(
            brief_block=ctx.get("brief_block"),
            creation_notes=ctx.get("creation_notes"),
            world=ctx.get("world"),
            characters=ctx.get("characters_compact") or ctx.get("characters"),
            prev=ctx.get("prev"),
            foreshadow=ctx.get("foreshadow"),
            timeline=ctx.get("timeline"),
            content=_cap(content, 12000),
        )},
    ]
    yield {"type": "status", "stage": "review", "message": "正在审读正文（可调用查询工具核实疑点）…"}
    tools, handlers = collect_tools(project_id, chapter_id, write=False)
    holder = {}
    try:
        async for ev in _run_with_tools(
            messages, tools, handlers, holder, emit_deltas=False, final_text_only=True,
        ):
            yield ev
    except LLMError as e:
        yield {"type": "error", "message": str(e)}
        return
    raw = holder.get("text", "")
    report = _parse_review_report(raw)
    if report is None:
        yield {"type": "status", "stage": "review", "message": "正在整理审校报告 JSON…"}
        retry_raw = []
        nudge = {
            "role": "user",
            "content": (
                "请根据你刚才的审读结论，严格只输出一个 JSON 对象，不要 markdown、不要调用工具、不要其它文字："
                '{"score":整数,"summary":"一句话总评","issues":[{"type":"一致性|情节|文风|节奏|伏笔",'
                '"severity":"高|中|低","location":"位置","description":"问题","suggestion":"改法"}]}'
            ),
        }
        try:
            async for ev in stream_chat(messages + [nudge], tools=None):
                if ev["type"] == "text":
                    retry_raw.append(ev["text"])
                    yield {"type": "output", "text": ev["text"]}
                elif ev["type"] == "reasoning":
                    yield ev
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
            return
        raw = "".join(retry_raw) or raw
        report = _parse_review_report(raw)
    if report is None:
        yield {"type": "error", "message": "审校结果解析失败", "raw": (raw or "")[:2000]}
        return
    issues = report.get("issues") or []
    score = int(report.get("score") or 0)
    round_no = db.query_one(
        "SELECT COUNT(*) AS n FROM reviews WHERE chapter_id=?", (chapter_id,)
    )["n"] + 1
    rid = db.execute(
        "INSERT INTO reviews(chapter_id, version_id, round, score, report, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (chapter_id, chapter["current_version_id"], round_no, score,
         json.dumps({"summary": report.get("summary", ""), "issues": issues}, ensure_ascii=False),
         db.now()),
    )
    yield {"type": "review", "review_id": rid, "round": round_no, "score": score,
           "issues": issues, "summary": report.get("summary", "")}
    yield {"type": "done", "stage": "review", "score": score}


async def run_revise(project_id, chapter_id):
    chapter = _chapter(chapter_id)
    if not chapter:
        yield {"type": "error", "message": "章节不存在"}
        return
    content = _current_content(chapter)
    review = db.query_one(
        "SELECT * FROM reviews WHERE chapter_id=? ORDER BY id DESC LIMIT 1", (chapter_id,)
    )
    if not content:
        yield {"type": "error", "message": "本章还没有正文"}
        return
    if not review:
        yield {"type": "error", "message": "还没有审校报告，请先审校"}
        return
    report = db.jload(review["report"], {})
    issues = report.get("issues") or []
    if not issues:
        yield {"type": "error", "message": "最近一次审校没有修订意见，无需修订"}
        return
    issues_text = "\n".join(
        f"{i}. [{it.get('severity', '中')}/{it.get('type', '')}] 位置：{it.get('location', '-')}\n"
        f"   问题：{it.get('description', '')}\n   建议：{it.get('suggestion', '')}"
        for i, it in enumerate(issues, 1)
    )
    yield {"type": "status", "stage": "revise", "message": f"正在按 {len(issues)} 条意见修订…"}
    system = prompts.REVISE_SYSTEM.format(skills_block=build_skills_block("revise"))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompts.REVISE_USER.format(
            content=_cap(content, 12000), issues=issues_text)},
    ]
    tools, handlers = collect_tools(project_id, chapter_id, write=True)
    holder = {}
    try:
        async for ev in _run_with_tools(messages, tools, handlers, holder):
            yield ev
    except LLMError as e:
        yield {"type": "error", "message": str(e)}
        return
    text = holder.get("text", "")
    if not text.strip():
        yield {"type": "error", "message": "模型未返回修订稿"}
        return
    saved = _save_version(chapter_id, "revise", text, review_id=review["id"], note="Agent 修订")
    yield {"type": "version_saved", "vtype": "revise", **saved}
    for ev in await _auto_summary(_chapter(chapter_id)):
        yield ev
    yield {"type": "done", "stage": "revise", **saved}


# ---------------------------------------------------------------- 自动循环

async def run_auto(project_id, chapter_id, rounds=None, mode="full"):
    """全自动：draft_only=仅初稿；full=[初稿→审校]→(修订→审校)×N；polish=仅审校修订已有稿。"""
    cfg = db.get_config()
    max_rounds = rounds or db.cfg_int(cfg, "agent_rounds", 2)
    threshold = db.cfg_int(cfg, "review_threshold", 85)
    yield {"type": "phase", "phase": "start", "rounds": max_rounds, "threshold": threshold, "mode": mode}

    if mode == "draft_only":
        yield {"type": "phase", "phase": "draft", "round": 1}
        async for ev in run_draft(project_id, chapter_id, lite=True, skip_summary=True):
            if ev.get("type") == "error":
                yield ev
                return
            if ev.get("type") != "done":
                yield ev
        yield {"type": "done", "stage": "auto", "final_score": 0, "rounds": 1, "mode": mode}
        return

    final_score, used_rounds = 0, 0
    for rnd in range(1, max_rounds + 1):
        used_rounds = rnd
        if rnd == 1 and mode == "full":
            yield {"type": "phase", "phase": "draft", "round": rnd}
            async for ev in run_draft(project_id, chapter_id):
                if ev.get("type") == "error":
                    yield ev
                    return
                if ev.get("type") != "done":
                    yield ev
        yield {"type": "phase", "phase": "review", "round": rnd}
        score = None
        async for ev in run_review(project_id, chapter_id):
            if ev.get("type") == "error":
                yield ev
                return
            if ev.get("type") == "review":
                score = ev["score"]
                yield ev
        final_score = score or 0
        if score is not None and score >= threshold:
            break
        if rnd < max_rounds:
            yield {"type": "phase", "phase": "revise", "round": rnd}
            async for ev in run_revise(project_id, chapter_id):
                if ev.get("type") == "error":
                    yield ev
                    return
                if ev.get("type") != "done":
                    yield ev
    yield {"type": "done", "stage": "auto", "final_score": final_score, "rounds": used_rounds}


# ---------------------------------------------------------------- JSON 解析

def _coerce_review_report(raw: str):
    """从非标准输出中尽量提取审校报告。"""
    if not raw:
        return None
    m = re.search(r'"score"\s*:\s*(\d+)', raw)
    if not m:
        return None
    score = int(m.group(1))
    summary_m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    summary = summary_m.group(1) if summary_m else "（模型未给出总评，已自动提取分数）"
    return {"score": score, "summary": summary, "issues": []}


def _parse_review_report(raw: str):
    data = extract_json(raw)
    if not isinstance(data, dict):
        data = _coerce_review_report(raw)
    if not isinstance(data, dict) or "score" not in data:
        return None
    try:
        score = int(float(data.get("score", 0)))
    except (TypeError, ValueError):
        return None
    issues = data.get("issues")
    if not isinstance(issues, list):
        issues = []
    summary = str(data.get("summary") or "").strip() or "（无总评）"
    return {"score": score, "summary": summary, "issues": issues}


def extract_json(text: str):
    """从模型输出中稳健地提取第一个完整 JSON 对象/数组（以更早出现者为准）。"""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    pairs = []
    pos_obj = text.find("{")
    if pos_obj >= 0:
        pairs.append((pos_obj, "{", "}"))
    pos_arr = text.find("[")
    if pos_arr >= 0:
        pairs.append((pos_arr, "[", "]"))
    pairs.sort(key=lambda p: p[0])
    for start, opener, closer in pairs:
        depth, in_str, escape = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
    return None
