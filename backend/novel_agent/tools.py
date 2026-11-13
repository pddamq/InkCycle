"""Agent 工具层：内置书籍工具（查询类 + 写入类）+ MCP 工具（命名空间合并）。

设计目标：让写作 Agent 在生成/修订时能"边写边核对、边写边登记"——
- 查询类工具：核对人物、设定、伏笔、前文、时间线，保证一致性；
- 写入类工具：把本章新埋的伏笔、新发生的事件自动写回数据库，
  使伏笔台账/时间线随剧情自动维护，供后续章节与审校使用。

MCP 工具名映射：mcp__{server}__{tool}，执行时反查连接。
处理器可以是同步函数（内置工具）或异步函数（MCP 工具），由 agent 统一调度。
"""
import re

from . import db
from .mcp import manager as mcp_manager


# ---------------------------------------------------------------- 工具 Schema

def _fn(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


READ_SCHEMAS = [
    _fn("list_characters",
        "列出本书全部角色的姓名、定位与一句话性格。需要总览人物阵容或确认某角色是否已存在时使用。"),
    _fn("get_character_details",
        "按姓名查询单个角色的完整人物卡（外貌/性格/目标/秘密/关系/近况）。写对话或关键情节前核对该角色设定时使用。",
        {"name": {"type": "string", "description": "人物姓名（可模糊）"}}, ["name"]),
    _fn("get_world_setting",
        "查询世界观设定。keyword 留空返回全部小节标题与摘要；传入关键词返回匹配小节的完整内容。涉及力量体系、地理、势力、专有名词时使用。",
        {"keyword": {"type": "string", "description": "设定关键词，可留空"}}, []),
    _fn("list_open_foreshadowing",
        "列出本书所有尚未回收的伏笔（含埋设章节）。决定本章是否推进/回收某条伏笔时使用。"),
    _fn("search_previous_chapters",
        "在已写成正文的章节中全文搜索关键词，返回命中章节与上下文片段。核对前文是否提过某物/某人/某设定，避免前后矛盾时使用。",
        {"keyword": {"type": "string", "description": "搜索关键词"}}, ["keyword"]),
    _fn("get_recent_timeline",
        "获取本书最近的剧情时间线事件（按时间倒序）。核对时序、避免时间线冲突时使用。",
        {"count": {"type": "integer", "description": "返回条数，默认 10"}}, []),
    _fn("get_nearby_chapters",
        "获取当前章及其前后各章的标题、梗概与写作状态。用于衔接上文、并为后续章节预埋伏笔。"),
    _fn("semantic_search",
        "全书语义检索（TF-IDF）：用自然语言或关键词查找相关前文片段，比精确关键词搜索更适合模糊回忆、主题关联。",
        {"query": {"type": "string", "description": "检索语句或关键词"}}, ["query"]),
]

CHAT_SCHEMAS = [
    _fn("ask_user",
        "当存在关键创作决策不确定时，向用户提问并暂停本轮。提供 2-4 个选项供选择；禁止猜测后继续写稿。",
        {"question": {"type": "string", "description": "要问用户的问题"},
         "options": {"type": "array", "items": {"type": "string"}, "description": "可选答案，2-4 项"},
         "allow_custom": {"type": "boolean", "description": "是否允许自定义输入，默认 true"}},
        ["question"]),
]

WRITE_SCHEMAS = [
    _fn("register_foreshadowing",
        "登记一条本章新埋设的伏笔到台账（状态=待回收）。当正文中引入了将来需要解释/回收的悬念、道具、异常细节时调用，避免伏笔遗失。",
        {"description": {"type": "string", "description": "伏笔内容，一句话说清埋了什么"},
         "payoff_hint": {"type": "string", "description": "预计如何/何时回收（可留空）"}},
        ["description"]),
    _fn("resolve_foreshadowing",
        "将一条已埋设的伏笔标记为「已回收」（按描述模糊匹配台账中的待回收伏笔）。当本章揭晓/兑现了之前的悬念时调用。",
        {"description": {"type": "string", "description": "被回收的伏笔描述（与台账中文字相近即可）"}},
        ["description"]),
    _fn("add_timeline_event",
        "向时间线追加一条本章发生的关键剧情事件。用于维护故事时序，供后续章节与审校核对时间一致性。",
        {"time_label": {"type": "string", "description": "时间标签，如「第3夜」/「案发次日」/「三年前」"},
         "description": {"type": "string", "description": "事件内容"}},
        ["description"]),
    _fn("update_chapter",
        "提交完整章节正文到编辑器（覆盖）。写稿/改稿/扩写/局部修改时必用：以当前正文为底稿合并改动后，提交整章成稿；禁止在对话里粘贴正文。",
        {"content": {"type": "string", "description": "完整章节正文（非片段）"}}, ["content"]),
]


def _sanitize(name: str) -> str:
    return re.sub(r"\W", "_", name)


def _short(text, n=80):
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


# ---------------------------------------------------------------- 收集工具与处理器

def collect_tools(project_id: int, chapter_id: int = None, write: bool = False, chat: bool = False,
                  holder: dict = None, lite: bool = False):
    """返回 (OpenAI tools 参数, name→处理器 映射)。

    write=True 时附加写入类工具（登记伏笔/回收伏笔/记录时间线），
    写入工具需要 chapter_id 以关联到当前章。
    """
    handlers = {}

    # ---------------- 查询类 ----------------
    def h_list_characters(args):
        rows = db.query("SELECT * FROM characters WHERE project_id=? ORDER BY id", (project_id,))
        if not rows:
            return "本书暂无角色。"
        out = []
        for r in rows:
            p = db.jload(r["profile"], {})
            brief = p.get("personality") or p.get("goal") or ""
            out.append(f"- {r['name']}（{r['role'] or '角色'}）：{_short(brief, 60)}")
        return "\n".join(out)

    def h_get_character(args):
        name = (args.get("name") or "").strip()
        if not name:
            return "请提供人物姓名。"
        row = db.query_one(
            "SELECT * FROM characters WHERE project_id=? AND name LIKE ? ORDER BY id LIMIT 1",
            (project_id, f"%{name}%"),
        )
        if not row:
            names = [r["name"] for r in db.query(
                "SELECT name FROM characters WHERE project_id=? ORDER BY id", (project_id,))]
            return f"未找到人物「{name}」。现有角色：{('、'.join(names)) or '（无）'}"
        p = db.jload(row["profile"], {})
        lines = [f"姓名：{row['name']}", f"定位：{row['role'] or '—'}"]
        label = {"appearance": "外貌", "personality": "性格", "goal": "目标",
                 "secret": "秘密", "relationships": "关系", "recent": "近况"}
        for k, v in p.items():
            if v:
                lines.append(f"{label.get(k, k)}：{v}")
        return "\n".join(lines)

    def h_world_setting(args):
        keyword = (args.get("keyword") or "").strip()
        row = db.query_one("SELECT sections FROM world WHERE project_id=?", (project_id,))
        sections = db.jload(row["sections"], []) if row else []
        if not sections:
            return "本书暂无世界观设定。"
        if not keyword:
            return "世界观小节（可用 keyword 查询详情）：\n" + "\n".join(
                f"- {s.get('title','(无标题)')}：{_short(s.get('content',''), 60)}" for s in sections)
        hits = [s for s in sections
                if keyword in (s.get("title", "") + s.get("content", ""))]
        if not hits:
            return f"设定中未找到与「{keyword}」相关的小节。"
        return "\n\n".join(f"■ {s.get('title','')}\n{s.get('content','')}" for s in hits)

    def h_foreshadow(args):
        rows = db.query(
            "SELECT f.*, c.title AS planted_title FROM foreshadowing f "
            "LEFT JOIN chapters c ON c.id=f.planted_chapter_id "
            "WHERE f.project_id=? AND f.status='open' ORDER BY f.id",
            (project_id,),
        )
        if not rows:
            return "当前没有未回收的伏笔。"
        return "\n".join(
            f"- {r['description']}（埋于：{r['planted_title'] or '未登记'}）" for r in rows)

    def h_search(args):
        keyword = (args.get("keyword") or "").strip()
        if not keyword:
            return "请提供搜索关键词。"
        chapters = db.query(
            "SELECT id, title, current_version_id FROM chapters "
            "WHERE project_id=? AND current_version_id IS NOT NULL "
            "ORDER BY volume_id, idx", (project_id,))
        hits = []
        for ch in chapters:
            ver = db.query_one("SELECT content FROM chapter_versions WHERE id=?",
                               (ch["current_version_id"],))
            if not ver:
                continue
            text = ver["content"] or ""
            m = re.search(re.escape(keyword), text)
            if m:
                s = max(0, m.start() - 60)
                e = min(len(text), m.end() + 60)
                hits.append(f"《{ch['title']}》：…{text[s:e]}…".replace("\n", " "))
            if len(hits) >= 8:
                break
        return "\n".join(hits) if hits else f"前文正文中未出现「{keyword}」。"

    def h_timeline(args):
        count = args.get("count") or 10
        rows = db.query(
            "SELECT t.*, c.title AS chapter_title FROM timeline_events t "
            "LEFT JOIN chapters c ON c.id=t.chapter_id "
            "WHERE t.project_id=? ORDER BY t.idx DESC, t.id DESC LIMIT ?",
            (project_id, int(count)))
        if not rows:
            return "时间线暂无事件。"
        return "\n".join(
            f"- {r['time_label'] or '(无时间标签)'}：{r['description']}（{r['chapter_title'] or '未关联章节'}）"
            for r in rows)

    def h_nearby_chapters(args):
        if not chapter_id:
            return "无当前章上下文。"
        cur = db.query_one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
        if not cur:
            return "当前章不存在。"
        rows = db.query(
            "SELECT id, title, brief, status, idx, volume_id FROM chapters "
            "WHERE project_id=? ORDER BY volume_id, idx", (project_id,))
        order = [r["id"] for r in rows]
        i = order.index(chapter_id) if chapter_id in order else -1
        lo, hi = max(0, i - 2), min(len(rows), i + 3)
        out = []
        for r in rows[lo:hi]:
            mark = "▶当前章" if r["id"] == chapter_id else ("✓已写" if r["status"] in ("drafted", "reviewed", "final") else "待写")
            out.append(f"[{mark}] {r['title']}：{_short(r['brief'], 100) or '(无梗概)'}")
        return "\n".join(out)

    handlers["list_characters"] = h_list_characters
    handlers["get_character_details"] = h_get_character
    handlers["get_world_setting"] = h_world_setting
    handlers["list_open_foreshadowing"] = h_foreshadow
    handlers["search_previous_chapters"] = h_search
    handlers["get_recent_timeline"] = h_timeline
    def h_semantic_search(args):
        from .rag import semantic_search as rag_search
        q = (args.get("query") or "").strip()
        if not q:
            return "请提供检索语句。"
        hits = rag_search(project_id, q, limit=6, exclude_chapter_id=chapter_id)
        if not hits:
            return f"全书语义检索未找到与「{q}」相关的前文。"
        return "\n".join(
            f"- 《{h['title']}》(相关度{h['score']})：{h['snippet']}" for h in hits)

    handlers["get_nearby_chapters"] = h_nearby_chapters
    handlers["semantic_search"] = h_semantic_search

    if lite:
        lite_names = {"list_characters", "get_nearby_chapters"}
        tools = [t for t in READ_SCHEMAS if t["function"]["name"] in lite_names]
        return tools, {k: v for k, v in handlers.items() if k in lite_names}

    tools = list(READ_SCHEMAS)

    # ---------------- 写入类（仅 write=True）----------------
    if write:
        def h_register_foreshadow(args):
            desc = (args.get("description") or "").strip()
            if not desc:
                return "登记失败：description 不能为空。"
            if not chapter_id:
                return "登记失败：无当前章上下文。"
            # 去重：已有相同/高度相似的待回收伏笔则不重复登记
            head = desc[:12]
            dup = db.query_one(
                "SELECT id FROM foreshadowing WHERE project_id=? AND status='open' AND description LIKE ?",
                (project_id, f"%{head}%"))
            if dup:
                return f"该伏笔已在台账中（#{dup['id']}），无需重复登记。"
            fid = db.execute(
                "INSERT INTO foreshadowing(project_id, description, planted_chapter_id, status, note, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (project_id, desc, chapter_id, "open", (args.get("payoff_hint") or "")[:300], db.now()))
            return f"已登记伏笔 #{fid}：{desc}"

        def h_resolve_foreshadow(args):
            desc = (args.get("description") or "").strip()
            if not desc:
                return "回收失败：description 不能为空。"
            head = desc[:10]
            row = db.query_one(
                "SELECT * FROM foreshadowing WHERE project_id=? AND status='open' AND description LIKE ? ORDER BY id LIMIT 1",
                (project_id, f"%{head}%"))
            if not row:
                return f"未找到与「{desc}」匹配的待回收伏笔。"
            db.execute(
                "UPDATE foreshadowing SET status='paid', payoff_chapter_id=? WHERE id=?",
                (chapter_id, row["id"]))
            return f"已标记伏笔 #{row['id']} 为已回收：{row['description']}"

        def h_add_timeline(args):
            desc = (args.get("description") or "").strip()
            if not desc:
                return "记录失败：description 不能为空。"
            mx = db.query_one(
                "SELECT COALESCE(MAX(idx),-1) AS m FROM timeline_events WHERE project_id=?",
                (project_id,))["m"]
            eid = db.execute(
                "INSERT INTO timeline_events(project_id, chapter_id, time_label, description, idx, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (project_id, chapter_id, (args.get("time_label") or "")[:60], desc, mx + 1, db.now()))
            return f"已记录时间线事件 #{eid}：{desc}"

        def h_update_chapter(args):
            content = (args.get("content") or "").strip()
            if not content:
                return "写入失败：content 不能为空。"
            wid = len(re.sub(r"\s", "", content))
            return f"已写入编辑器（{wid}字）。"

        handlers["register_foreshadowing"] = h_register_foreshadow
        handlers["resolve_foreshadowing"] = h_resolve_foreshadow
        handlers["add_timeline_event"] = h_add_timeline
        handlers["update_chapter"] = h_update_chapter
        tools = tools + list(WRITE_SCHEMAS)

    if chat:
        def h_ask_user(args):
            q = (args.get("question") or "").strip()
            opts = args.get("options") or []
            if not q:
                return "提问失败：question 不能为空。"
            if holder is not None:
                holder["ask_user"] = {
                    "question": q,
                    "options": [str(o) for o in opts][:6],
                    "allow_custom": args.get("allow_custom", True),
                }
            return "已向用户提问，请等待用户在界面回答后再继续。"

        handlers["ask_user"] = h_ask_user
        tools = tools + list(CHAT_SCHEMAS)

    # ---------------- 合并已连接 MCP 服务器的工具 ----------------
    for conn in mcp_manager.connected():
        for t in conn.tools[:20]:
            tool_name = f"mcp__{_sanitize(conn.name)}__{t['name']}"
            schema = dict(t["inputSchema"] or {})
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"[MCP:{conn.name}] {t['description'][:300]}",
                    "parameters": schema,
                },
            })
            handlers[tool_name] = _make_mcp_handler(conn, t["name"])

    return tools, handlers


def _make_mcp_handler(conn, tool_name: str):
    async def handler(args):
        return await conn.call_tool(tool_name, args or {})
    return handler
