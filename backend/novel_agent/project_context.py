"""同一本书的 AI 上下文统一组装 + 按优先级裁剪。

所有项目内 AI 功能（向导、角色设计、写作、审校等）应通过 assemble() 获取一致上下文，
避免各模块各取一段、互相看不见。
"""
from __future__ import annotations

import json

from . import db
from .prompts import IMITATE_WRITING_GUIDE

# ---------------------------------------------------------------- 蓝图字段

BRIEF_LABELS = {
    "subgenre": "子类型", "logline": "一句话创意", "theme": "主题内核", "audience": "目标读者",
    "tone": "基调", "era_setting": "时代背景", "world_rules": "世界规则", "main_scenes": "主要场景",
    "factions": "势力结构", "protagonist": "主角", "antagonist": "对手", "supporting": "配角与感情线",
    "relationships": "人物关系", "core_conflict": "核心冲突", "opening_hook": "开篇钩子",
    "plot_direction": "主要走向", "ending": "结局", "emotional_beats": "情绪与爽点",
    "pov": "视角人称", "style": "文风", "pacing": "节奏", "taboos": "禁忌雷点",
    "must_have": "必须包含", "references": "对标作品", "extra": "其他",
}

BRIEF_KEYS = {
    "settings": ["subgenre", "theme", "audience", "tone", "era_setting", "world_rules",
                 "main_scenes", "factions", "taboos", "must_have", "references"],
    "characters": ["theme", "tone", "subgenre", "protagonist", "antagonist",
                   "supporting", "relationships", "core_conflict", "taboos"],
    "outline": ["logline", "theme", "core_conflict", "opening_hook", "plot_direction",
                "ending", "emotional_beats", "pacing", "pov", "tone", "must_have"],
    "writing": ["logline", "theme", "core_conflict", "tone", "taboos", "must_have",
                "emotional_beats", "pacing", "pov", "references"],
}

# 各功能总字符预算（含所有块）
FEATURE_BUDGET = {
    "wizard_settings": 9000,
    "wizard_characters": 10000,
    "wizard_outline": 12000,
    "character_interview": 12000,
    "character_compile": 14000,
    "draft": 18000,
    "chat": 16000,
    "review": 14000,
    "revise": 10000,
}

# 块优先级：靠前更重要，超预算时从末尾块开始裁
FEATURE_PRIORITY = {
    "wizard_settings": ["brief_block", "creation_notes", "world", "characters_compact", "outline_compact"],
    "wizard_characters": ["brief_block", "creation_notes", "char_design_notes", "world", "characters", "outline_compact"],
    "wizard_outline": ["brief_block", "creation_notes", "world", "characters", "outline_compact", "foreshadow", "timeline"],
    "character_interview": ["brief_block", "creation_notes", "char_design_notes", "world", "characters", "outline_compact"],
    "character_compile": ["brief_block", "creation_notes", "char_design_notes", "world", "characters", "outline_compact"],
    "draft": ["brief_block", "creation_notes", "style", "world", "characters", "outline_compact", "prev", "foreshadow", "timeline"],
    "chat": ["brief_block", "creation_notes", "style", "world", "characters", "outline_compact", "prev", "foreshadow"],
    "review": ["brief_block", "world", "characters", "prev", "foreshadow", "timeline"],
    "revise": ["brief_block", "world", "characters"],
}

BLOCK_MAX = {
    "brief_block": 4000,
    "creation_notes": 3000,
    "char_design_notes": 2500,
    "world": 3500,
    "characters": 3500,
    "characters_compact": 1500,
    "outline_compact": 2000,
    "foreshadow": 1000,
    "timeline": 1000,
    "prev": 2000,
    "style": 800,
}

BLOCK_MIN = {
    "brief_block": 600,
    "creation_notes": 0,
    "char_design_notes": 0,
    "world": 300,
    "characters": 300,
    "characters_compact": 200,
    "outline_compact": 0,
    "foreshadow": 0,
    "timeline": 0,
    "prev": 200,
    "style": 0,
}

_META_KEYS = frozenset({
    "style_profile", "imitate", "source", "creation_notes", "char_design_notes",
    "branch_name", "parent_project_id", "chat_summaries", "char_design_summarize",
})


def cap(text, limit: int, tail: bool = False) -> str:
    if not text or len(text) <= limit:
        return text or ""
    clipped = text[-limit:] if tail else text[:limit]
    return clipped + f"…（已截断，原文{len(text)}字）"


def render_history(history) -> str:
    if not history:
        return "（尚无记录）"
    lines = []
    for turn in history:
        role = turn.get("role", "user")
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "（尚无记录）"


def _brief_dict(project) -> dict:
    brief = db.jload(project.get("brief"), {}) if project else {}
    return brief if isinstance(brief, dict) else {}


def brief_block(project, stage: str | None = None) -> str:
    brief = _brief_dict(project)
    if not brief:
        return "（无，按常规发挥）"
    if stage == "full":
        keys = [k for k in BRIEF_LABELS if brief.get(k) and k not in _META_KEYS]
    elif stage:
        keys = BRIEF_KEYS.get(stage, [])
    else:
        keys = list(BRIEF_LABELS.keys())
    lines = [f"- {BRIEF_LABELS.get(k, k)}：{brief[k]}"
             for k in keys if brief.get(k) and k not in _META_KEYS]
    return "\n".join(lines) or "（无，按常规发挥）"


def creation_notes(project, limit: int = 3000) -> str:
    brief = _brief_dict(project)
    raw = brief.get("creation_notes") or ""
    return cap(str(raw).strip(), limit) if raw else "（无）"


def char_design_notes(project, limit: int = 2500) -> str:
    brief = _brief_dict(project)
    raw = brief.get("char_design_notes") or ""
    return cap(str(raw).strip(), limit) if raw else "（无）"


def style_block(project) -> str:
    brief = _brief_dict(project)
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
        return "（无）"
    block = "【文风档案】\n" + "\n".join(lines)
    if brief.get("imitate") or brief.get("source") == "imitated":
        ref = brief.get("source_title") or brief.get("references") or "参考书"
        block += (
            f"\n【仿写纪律·摘要】参考书《{ref}》仅借鉴文风；"
            "必须写全新故事、全新人物、全新专有名词与全新句子；"
            "禁止复用人名、地名、势力、情节桥段、原文措辞。"
        )
        block += IMITATE_WRITING_GUIDE
    return block


def world_text(pid: int, limit: int = 3500) -> str:
    row = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    sections = db.jload(row["sections"], []) if row else []
    parts = [f"■ {s.get('title', '')}\n{s.get('content', '')}"
             for s in sections if s.get("title") or s.get("content")]
    return cap("\n\n".join(parts), limit) or "（暂无设定）"


def world_digest(pid: int, limit: int = 2000) -> str:
    row = db.query_one("SELECT sections FROM world WHERE project_id=?", (pid,))
    sections = db.jload(row["sections"], []) if row else []
    parts = [f"{s.get('title', '')}：{cap(s.get('content', ''), 150)}"
             for s in sections if s.get("title") or s.get("content")]
    return cap("；".join(parts), limit) or "（暂无设定）"


def characters_text(pid: int, cap_each: int = 500, max_count: int = 12) -> str:
    rows = db.query("SELECT * FROM characters WHERE project_id=? ORDER BY id LIMIT ?", (pid, max_count))
    if not rows:
        return "（暂无人物）"
    blocks = []
    for r in rows:
        profile = db.jload(r["profile"], {})
        lines = [f"{r['name']}（{r['role']}）"]
        for k, v in profile.items():
            if v:
                lines.append(f"  · {k}：{cap(str(v), 160)}")
        blocks.append(cap("\n".join(lines), cap_each))
    extra = db.query_one("SELECT COUNT(*) AS n FROM characters WHERE project_id=?", (pid,))["n"]
    text = "\n".join(blocks)
    if extra > max_count:
        text += f"\n…（另有 {extra - max_count} 个角色未展开，可用工具查询）"
    return text


def characters_compact(pid: int, limit: int = 1500) -> str:
    rows = db.query("SELECT name, role, profile FROM characters WHERE project_id=? ORDER BY id", (pid,))
    if not rows:
        return "（暂无人物）"
    out = []
    for r in rows:
        profile = db.jload(r["profile"], {})
        brief = profile.get("personality") or profile.get("goal") or ""
        out.append(f"{r['name']}（{r['role']}）：{cap(str(brief), 80)}")
    return cap("\n".join(out), limit)


def existing_chars_line(pid: int) -> str:
    rows = db.query("SELECT name, role, profile FROM characters WHERE project_id=? ORDER BY id", (pid,))
    if not rows:
        return "（暂无，将从零设计）"
    lines = []
    for r in rows:
        profile = db.jload(r["profile"], {})
        goal = profile.get("goal", "")
        lines.append(f"- {r['name']}（{r['role']}）" + (f"：{goal[:40]}" if goal else ""))
    return "\n".join(lines)


def outline_compact(pid: int, limit: int = 2000, max_chapters: int = 24) -> str:
    rows = db.query(
        "SELECT c.title, c.brief, v.title AS vol FROM chapters c "
        "JOIN volumes v ON v.id=c.volume_id "
        "WHERE c.project_id=? ORDER BY v.idx, c.idx LIMIT ?",
        (pid, max_chapters),
    )
    if not rows:
        return "（暂无大纲）"
    lines = []
    cur_vol = None
    for r in rows:
        if r["vol"] != cur_vol:
            cur_vol = r["vol"]
            lines.append(f"■ {cur_vol}")
        lines.append(f"  - {r['title']}：{cap(r['brief'] or '（无梗概）', 100)}")
    total = db.query_one("SELECT COUNT(*) AS n FROM chapters WHERE project_id=?", (pid,))["n"]
    text = "\n".join(lines)
    if total > max_chapters:
        text += f"\n…（全书共 {total} 章，仅展示前 {max_chapters} 章梗概）"
    return cap(text, limit)


def foreshadow_text(pid: int, chapter_id: int | None = None, limit: int = 1000) -> str:
    rows = db.query(
        "SELECT f.*, c.title AS planted_title FROM foreshadowing f "
        "LEFT JOIN chapters c ON c.id=f.planted_chapter_id "
        "WHERE f.project_id=? AND f.status='open' ORDER BY f.id",
        (pid,),
    )
    if not rows:
        return "（暂无待处理伏笔）"
    out = []
    for r in rows:
        mine = "（可埋设/推进）" if not r["planted_chapter_id"] else f"（已埋于《{r['planted_title']}》）"
        out.append(f"- {r['description']}{mine}")
    return cap("\n".join(out), limit)


def timeline_text(pid: int, limit: int = 1000) -> str:
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
    return cap("\n".join(lines), limit)


def prev_text(chapter, limit: int = 2000) -> str:
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
        ver = db.query_one("SELECT content FROM chapter_versions WHERE id=?", (prev_ch["current_version_id"],))
        if ver and ver["content"]:
            parts.append(f"【上一章结尾】\n{cap(ver['content'], 400, tail=True)}")
    return cap("\n\n".join(parts), limit)


def _trim_blocks(blocks: dict[str, str], priority: list[str], budget: int) -> dict[str, str]:
    total = sum(len(blocks.get(k) or "") for k in priority)
    if total <= budget:
        return blocks
    result = dict(blocks)
    overflow = total - budget
    for key in reversed(priority):
        if overflow <= 0:
            break
        text = result.get(key) or ""
        if not text or text in ("（无）", "（暂无设定）", "（暂无人物）", "（暂无大纲）", "（尚无记录）"):
            continue
        min_keep = BLOCK_MIN.get(key, 0)
        can_trim = max(0, len(text) - min_keep)
        if can_trim <= 0:
            continue
        trim_amt = min(overflow, can_trim)
        new_len = len(text) - trim_amt
        result[key] = cap(text, new_len)
        overflow -= trim_amt
    return result


class AssembledContext:
    """assemble() 的返回值：dict 式访问 + 模板 format 辅助。"""

    def __init__(self, blocks: dict[str, str], project, pid: int, feature: str):
        self.blocks = blocks
        self.project = project
        self.pid = pid
        self.feature = feature

    def get(self, key: str, default: str = "") -> str:
        return self.blocks.get(key, default)

    def __getitem__(self, key: str) -> str:
        return self.blocks[key]

    def for_template(self) -> dict:
        """供 str.format 使用的扁平 dict（含书名等元信息）。"""
        p = self.project or {}
        out = dict(self.blocks)
        defaults = {
            "creation_notes": "（无）",
            "char_design_notes": "（无）",
            "outline_compact": "（暂无大纲）",
            "outline_snippet": "（暂无大纲）",
            "foreshadow": "（暂无待处理伏笔）",
            "timeline": "（时间线暂无事件）",
            "style_block": self.blocks.get("style") or "（无）",
        }
        for k, v in defaults.items():
            out.setdefault(k, v)
        out["outline_snippet"] = out.get("outline_compact") or out["outline_snippet"]
        out.update({
            "title": p.get("title") or "",
            "genre": p.get("genre") or "未指定",
            "premise": p.get("premise") or "（待补充）",
            "style": p.get("style") or "未指定",
            "target": p.get("target_words") or 200000,
            "existing_chars": existing_chars_line(self.pid),
            "world": out.get("world") or world_digest(self.pid),
            "characters": out.get("characters") or characters_compact(self.pid),
        })
        return out


def assemble(pid: int, feature: str, chapter_id: int | None = None, stage: str | None = None) -> AssembledContext:
    """按功能组装并裁剪同一本书的共享上下文。"""
    project = db.query_one("SELECT * FROM projects WHERE id=?", (pid,))
    if not project:
        raise ValueError("项目不存在")

    stage = stage or {
        "wizard_settings": "settings",
        "wizard_characters": "characters",
        "wizard_outline": "outline",
        "character_interview": "characters",
        "character_compile": "full",
        "draft": "writing",
        "chat": "writing",
        "review": "writing",
        "revise": "writing",
    }.get(feature, "full")

    brief_stage = "full" if stage == "full" else stage
    chapter = db.query_one("SELECT * FROM chapters WHERE id=?", (chapter_id,)) if chapter_id else None

    raw_blocks = {
        "brief_block": brief_block(project, brief_stage),
        "creation_notes": creation_notes(project, BLOCK_MAX["creation_notes"]),
        "char_design_notes": char_design_notes(project, BLOCK_MAX["char_design_notes"]),
        "style": style_block(project),
        "world": world_text(pid, BLOCK_MAX["world"]) if feature in ("draft",) else world_digest(pid, BLOCK_MAX["world"]),
        "characters": characters_text(pid),
        "characters_compact": characters_compact(pid, BLOCK_MAX["characters_compact"]),
        "outline_compact": outline_compact(pid, BLOCK_MAX["outline_compact"]),
        "foreshadow": foreshadow_text(pid, chapter_id, BLOCK_MAX["foreshadow"]) if chapter_id else foreshadow_text(pid, None, BLOCK_MAX["foreshadow"]),
        "timeline": timeline_text(pid, BLOCK_MAX["timeline"]),
        "prev": prev_text(chapter, BLOCK_MAX["prev"]) if chapter else "（非章节上下文）",
    }

    if feature in ("chat", "review"):
        raw_blocks["characters"] = raw_blocks["characters_compact"]

    # 单块上限
    for key, mx in BLOCK_MAX.items():
        if key in raw_blocks and raw_blocks[key]:
            raw_blocks[key] = cap(raw_blocks[key], mx)

    priority = FEATURE_PRIORITY.get(feature, list(raw_blocks.keys()))
    budget = FEATURE_BUDGET.get(feature, 12000)
    trimmed = _trim_blocks(raw_blocks, priority, budget)

    return AssembledContext(trimmed, project, pid, feature)


def merge_brief_meta(project_id: int, updates: dict) -> None:
    """向 projects.brief JSON 合并元数据（creation_notes / char_design_notes 等）。"""
    row = db.query_one("SELECT brief FROM projects WHERE id=?", (project_id,))
    if not row:
        return
    brief = db.jload(row.get("brief"), {}) or {}
    if not isinstance(brief, dict):
        brief = {}
    brief.update(updates)
    db.execute(
        "UPDATE projects SET brief=?, updated_at=? WHERE id=?",
        (json.dumps(brief, ensure_ascii=False), db.now(), project_id),
    )


def save_creation_notes(project_id: int, history, transcript=None) -> None:
    """保存开书访谈纪要到 brief.creation_notes。"""
    parts = []
    if transcript:
        for m in transcript:
            role = "作者" if m.get("role") == "user" else "编辑"
            if m.get("role") == "user":
                parts.append(f"{role}：{m.get('text', '')}")
            else:
                intro = m.get("intro") or ""
                qs = m.get("questions") or []
                qtxt = "；".join(f"{q.get('label', '')}：{q.get('text', '')}" for q in qs)
                if intro or qtxt:
                    parts.append(f"{role}：{intro}\n{qtxt}".strip())
    parts.append(render_history(history))
    text = cap("\n\n".join(p for p in parts if p), 6000)
    merge_brief_meta(project_id, {"creation_notes": text})


def save_char_design_notes(project_id: int, history) -> None:
    merge_brief_meta(project_id, {"char_design_notes": cap(render_history(history), 6000)})
