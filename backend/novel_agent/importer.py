"""导入书籍：解码、按标题拆卷/章、落库、文风与剧情分析。"""
import asyncio
import json
import re

from . import db
from .agent import _save_version, count_words, extract_json, chat
from .llm import stream_chat, LLMError, stream_progress_hint
from . import prompts

CHAPTER_CAP = 2000
FULL_CHAPTER_CAP = 1200
STYLE_SAMPLE = 1600
PLOT_BATCH = 8
PLOT_CONCURRENCY = 6
SMALL_BOOK_FULL = 80
OPENING_KEY = 30
MAX_KEY_CHAPTERS = 150
_TITLE_KEY = re.compile(
    r"大战|决战|揭秘|真相|转折|危机|高潮|结局|终章|尾声|复活|背叛|告白|突破|觉醒|陨落|暴露|番外|楔子|危机",
    re.I,
)

# 卷标题 / 章标题（行首）
_VOL = re.compile(
    r"^[ \t\u3000#【\[]*(第[0-9零〇一二三四五六七八九十百千万两]+[卷部集]"
    r"|Volume\s+\d+)[】\]]?[^\n]{0,40}$",
    re.I,
)
_CH = re.compile(
    r"^[ \t\u3000#【\[]*(第[0-9零〇一二三四五六七八九十百千万两]+[章节回]"
    r"|Chapter\s+\d+"
    r"|楔子|序章|序言|前言|引子|Prologue"
    r"|尾声|后记|番外[^\n]{0,20}|Epilogue)[】\]]?[^\n]{0,50}$",
    re.I,
)


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def guess_title(text: str, filename: str = "") -> str:
    stem = re.sub(r"\.(txt|md|markdown)$", "", filename or "", flags=re.I).strip()
    if stem and stem not in ("book", "novel", "untitled"):
        return stem[:40]
    for line in (text or "").splitlines():
        s = line.strip().lstrip("#").strip()
        if 2 <= len(s) <= 30 and not _CH.match(s) and not _VOL.match(s):
            return s
    return "导入作品"


def _clean_heading(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^#{1,6}\s*", "", s)
    s = s.strip("【】[] \t\u3000")
    return s or "未命名"


def split_book(text: str, filename: str = "") -> dict:
    """规则拆卷/章。无标题时按篇幅切块。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    title = guess_title(raw, filename)
    lines = raw.split("\n")

    marks = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if _VOL.match(s):
            marks.append((i, "vol", _clean_heading(s)))
        elif _CH.match(s):
            marks.append((i, "ch", _clean_heading(s)))

    volumes = []
    if marks:
        current_vol = {"title": "正文", "chapters": []}
        for n, (idx, kind, name) in enumerate(marks):
            end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
            body = "\n".join(lines[idx + 1:end]).strip()
            if kind == "vol":
                if current_vol["chapters"] or (current_vol["title"] != "正文"):
                    volumes.append(current_vol)
                current_vol = {"title": name, "chapters": []}
                if body:
                    current_vol["chapters"].append({"title": name, "content": body})
            else:
                current_vol["chapters"].append({"title": name, "content": body})
        if current_vol["chapters"] or current_vol["title"] != "正文":
            volumes.append(current_vol)
        # 丢掉空章
        for v in volumes:
            v["chapters"] = [c for c in v["chapters"] if (c.get("content") or "").strip()]
        volumes = [v for v in volumes if v["chapters"]]

    if not volumes:
        chunks = _split_by_size(raw)
        volumes = [{"title": "正文", "chapters": chunks}]

    for v in volumes:
        for c in v["chapters"]:
            c["words"] = count_words(c["content"])
    return {
        "title": title,
        "words": sum(c["words"] for v in volumes for c in v["chapters"]),
        "volume_count": len(volumes),
        "chapter_count": sum(len(v["chapters"]) for v in volumes),
        "volumes": volumes,
    }


def _split_by_size(text: str, target=2800) -> list:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        body = text.strip()
        return [{"title": "正文", "content": body}] if body else []
    chunks, buf = [], []
    n = 0
    idx = 1
    for p in paras:
        buf.append(p)
        n += len(p)
        if n >= target:
            chunks.append({"title": f"第{idx}章", "content": "\n\n".join(buf)})
            buf, n, idx = [], 0, idx + 1
    if buf:
        if chunks and n < target * 0.4:
            chunks[-1]["content"] += "\n\n" + "\n\n".join(buf)
        else:
            chunks.append({"title": f"第{idx}章", "content": "\n\n".join(buf)})
    return chunks


def persist_import(title: str, genre: str, volumes: list, filename: str = "") -> int:
    words = sum(count_words(c.get("content") or "") for v in volumes for c in v.get("chapters") or [])
    brief = json.dumps({
        "source": "imported",
        "imported_file": filename or "",
        "chapter_words": max(1500, min(8000, words // max(1, sum(len(v.get("chapters") or []) for v in volumes)))),
        "target_words": words,
    }, ensure_ascii=False)
    pid = db.execute(
        "INSERT INTO projects(title, genre, premise, style, target_words, brief, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (title[:80] or "导入作品", genre or "", f"由《{title or '未知'}》导入拆章", "",
         max(words, 10000), brief, db.now(), db.now()),
    )
    db.execute("INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?)",
               (pid, "[]", db.now()))
    for vi, vol in enumerate(volumes):
        vtitle = (vol.get("title") or f"第{vi + 1}卷").strip()
        vid = db.execute(
            "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
            (pid, vi, vtitle, ""),
        )
        for ci, ch in enumerate(vol.get("chapters") or []):
            ctitle = (ch.get("title") or f"第{ci + 1}章").strip()
            content = (ch.get("content") or "").strip()
            chid = db.execute(
                "INSERT INTO chapters(project_id, volume_id, idx, title, brief, status, "
                "word_count, book_done, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid, vid, ci, ctitle, "", "final", count_words(content), 1, db.now(), db.now()),
            )
            if content:
                _save_version(chid, "manual", content, note="导入原文")
                db.execute(
                    "UPDATE chapters SET status='final', book_done=1, updated_at=? WHERE id=?",
                    (db.now(), chid),
                )
    return pid


def _merge_brief(pid: int, updates: dict):
    row = db.query_one("SELECT brief FROM projects WHERE id=?", (pid,))
    brief = db.jload(row["brief"] if row else "{}", {}) or {}
    if not isinstance(brief, dict):
        brief = {}
    brief.update(updates)
    db.execute("UPDATE projects SET brief=?, updated_at=? WHERE id=?",
               (json.dumps(brief, ensure_ascii=False), db.now(), pid))
    return brief


def _sample_chapters(pid: int, each=STYLE_SAMPLE) -> str:
    rows = db.query(
        "SELECT c.title, v.content FROM chapters c "
        "JOIN chapter_versions v ON v.id=c.current_version_id "
        "WHERE c.project_id=? ORDER BY c.volume_id, c.idx", (pid,))
    if not rows:
        return ""
    picks = [rows[0]]
    if len(rows) > 2:
        picks.append(rows[len(rows) // 2])
    if len(rows) > 1:
        picks.append(rows[-1])
    seen, parts = set(), []
    for r in picks:
        if r["title"] in seen:
            continue
        seen.add(r["title"])
        parts.append(f"《{r['title']}》\n{(r['content'] or '')[:each]}")
    return "\n\n".join(parts)


async def _stream_llm_collect(messages, *, status_msg: str):
    """流式 LLM：推送思考/进度，末尾 _end 携带完整原文（勿展示给前端）。"""
    yield {"type": "status", "message": status_msg}
    parts = []
    try:
        async for ev in stream_chat(messages):
            if ev["type"] == "reasoning":
                yield ev
            elif ev["type"] == "text":
                parts.append(ev["text"])
                full = "".join(parts)
                yield {"type": "delta", "text": ev["text"]}
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


def _apply_style_profile(pid: int, data: dict) -> dict:
    style = (data.get("style_summary") or "").strip()
    genre = (data.get("genre") or "").strip()
    try:
        cw = int(data.get("chapter_words") or 0)
    except (TypeError, ValueError):
        cw = 0
    sets, args = ["style=?", "updated_at=?"], [style, db.now()]
    if genre:
        sets.append("genre=?")
        args.append(genre)
    args.append(pid)
    db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", tuple(args))
    extra = {"style_profile": data, "style": style}
    if data.get("pov"):
        extra["pov"] = data["pov"]
    if data.get("pacing"):
        extra["pacing"] = data["pacing"]
    if data.get("tone"):
        extra["tone"] = data["tone"]
    if cw:
        extra["chapter_words"] = cw
    _merge_brief(pid, extra)
    return data


async def analyze_style(pid: int, *, skip_if_done: bool = False):
    """异步生成器：流式分析文风，最后 yield style 事件。"""
    if skip_if_done:
        row = db.query_one("SELECT brief, style FROM projects WHERE id=?", (pid,))
        brief = db.jload(row["brief"] if row else "{}", {}) or {}
        if brief.get("style_profile") or (row and row.get("style")):
            yield {"type": "style", "profile": brief.get("style_profile") or {"style_summary": row.get("style") or ""}}
            return
    sample = _sample_chapters(pid)
    if not sample.strip():
        raise LLMError("没有可分析的正文")
    yield {"type": "phase", "phase": "解析文风"}
    messages = [
        {"role": "system", "content": prompts.STYLE_ANALYZE_SYSTEM},
        {"role": "user", "content": prompts.STYLE_ANALYZE_USER.format(sample=sample[:8000])},
    ]
    raw = ""
    async for ev in _stream_llm_collect(messages, status_msg="正在分析文风、叙事视角与节奏…"):
        if ev.get("type") == "_end":
            raw = ev.get("raw") or ""
        else:
            yield ev
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise LLMError("文风解析失败")
    profile = _apply_style_profile(pid, data)
    yield {"type": "style", "profile": profile}


def _chapter_rows(pid: int) -> list:
    return db.query(
        "SELECT c.id, c.title, c.idx, c.volume_id, v.content FROM chapters c "
        "LEFT JOIN chapter_versions v ON v.id=c.current_version_id "
        "WHERE c.project_id=? ORDER BY c.volume_id, c.idx", (pid,))


async def _llm_raw(messages) -> str:
    parts = []
    async for ev in stream_chat(messages):
        if ev["type"] == "text":
            parts.append(ev["text"])
    return "".join(parts)


def normalize_deep_ratio(ratio) -> int | None:
    """10～100，步进 10；None 表示沿用旧版智能选章（兼容历史项目）。"""
    if ratio is None:
        return None
    try:
        r = int(ratio)
    except (TypeError, ValueError):
        return None
    return max(10, min(100, round(r / 10) * 10))


def _project_deep_ratio(pid: int) -> int | None:
    row = db.query_one("SELECT brief FROM projects WHERE id=?", (pid,))
    brief = db.jload(row["brief"] if row else "{}", {}) or {}
    plot = brief.get("import_plot") or {}
    return normalize_deep_ratio(plot.get("deep_ratio"))


def _chapter_score(r: dict, idx: int, n: int, by_vol: dict) -> int:
    score = 0
    if idx < OPENING_KEY:
        score += 100
    if idx == n - 1:
        score += 90
    if _TITLE_KEY.search(r["title"] or ""):
        score += 50
    vol_rows = by_vol.get(r["volume_id"], [])
    if vol_rows:
        if r["id"] in (vol_rows[0]["id"], vol_rows[-1]["id"]):
            score += 40
        vn = len(vol_rows)
        if vn > 8:
            for frac in (0.25, 0.5, 0.75):
                if r["id"] == vol_rows[int(vn * frac)]["id"]:
                    score += 30
        elif vn > 3 and r["id"] == vol_rows[vn // 2]["id"]:
            score += 30
    return score


def _select_key_chapters_legacy(rows: list) -> set:
    """旧版智能选章：开篇 + 卷首尾 + 抽样 + 标题关键词，上限 MAX_KEY_CHAPTERS。"""
    n = len(rows)
    if n <= SMALL_BOOK_FULL:
        return {r["id"] for r in rows}
    picks = set()
    for r in rows[:OPENING_KEY]:
        picks.add(r["id"])
    picks.add(rows[-1]["id"])
    by_vol: dict = {}
    for r in rows:
        by_vol.setdefault(r["volume_id"], []).append(r)
    for vol_rows in by_vol.values():
        vn = len(vol_rows)
        picks.add(vol_rows[0]["id"])
        picks.add(vol_rows[-1]["id"])
        if vn > 8:
            for frac in (0.25, 0.5, 0.75):
                picks.add(vol_rows[int(vn * frac)]["id"])
        elif vn > 3:
            picks.add(vol_rows[vn // 2]["id"])
        for r in vol_rows:
            if _TITLE_KEY.search(r["title"] or ""):
                picks.add(r["id"])
    if len(picks) <= MAX_KEY_CHAPTERS:
        return picks
    priority = []
    seen = set()
    for i, r in enumerate(rows):
        if r["id"] not in picks or r["id"] in seen:
            continue
        priority.append((_chapter_score(r, i, n, by_vol), r["id"]))
        seen.add(r["id"])
    priority.sort(key=lambda x: (-x[0], x[1]))
    return {cid for _, cid in priority[:MAX_KEY_CHAPTERS]}


def _select_key_chapters(rows: list, deep_ratio: int | None = 10) -> set:
    """按全书比例挑选深度解析章；每段区间内优先选结构/标题更重要的章。"""
    n = len(rows)
    if n == 0:
        return set()
    if deep_ratio is None:
        return _select_key_chapters_legacy(rows)
    if deep_ratio >= 100:
        return {r["id"] for r in rows}
    target = max(1, round(n * deep_ratio / 100))
    if target >= n:
        return {r["id"] for r in rows}

    by_vol: dict = {}
    for r in rows:
        by_vol.setdefault(r["volume_id"], []).append(r)
    scored = [
        (_chapter_score(r, i, n, by_vol), i, r["id"])
        for i, r in enumerate(rows)
    ]
    picks = set()
    seg_size = n / target
    for k in range(target):
        start = int(k * seg_size)
        end = int((k + 1) * seg_size) if k < target - 1 else n
        if start >= end:
            continue
        _, _, cid = max(scored[start:end], key=lambda x: (x[0], -x[1]))
        picks.add(cid)
    return picks


def _apply_light_chapter(r: dict):
    title = (r["title"] or "").strip() or "未命名"
    db.execute(
        "UPDATE chapters SET summary=?, brief=?, updated_at=? WHERE id=?",
        ("", title, db.now(), r["id"]),
    )


def _apply_plot_item(pid: int, r: dict, it: dict, chars_seen: dict):
    summary = (it.get("summary") or "")[:300]
    brief = (it.get("brief") or summary)[:400]
    db.execute(
        "UPDATE chapters SET summary=?, brief=?, updated_at=? WHERE id=?",
        (summary, brief, db.now(), r["id"]),
    )
    for c in it.get("characters") or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name or name in chars_seen:
            continue
        chars_seen[name] = True
        profile = {k: c.get(k, "") for k in ("appearance", "personality", "goal", "secret", "relationships") if c.get(k)}
        if c.get("note"):
            profile.setdefault("personality", c["note"])
        db.execute(
            "INSERT INTO characters(project_id, name, role, profile, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (pid, name, str(c.get("role") or ""), json.dumps(profile, ensure_ascii=False),
             db.now(), db.now()),
        )
    for f in it.get("foreshadows") or []:
        if not isinstance(f, dict):
            continue
        desc = (f.get("description") or "").strip()
        if not desc:
            continue
        action = (f.get("action") or "plant").lower()
        if action in ("resolve", "payoff", "paid"):
            open_row = db.query_one(
                "SELECT id FROM foreshadowing WHERE project_id=? AND status='open' "
                "AND description LIKE ? ORDER BY id LIMIT 1",
                (pid, f"%{desc[:20]}%"),
            )
            if open_row:
                db.execute(
                    "UPDATE foreshadowing SET status='paid', payoff_chapter_id=? WHERE id=?",
                    (r["id"], open_row["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO foreshadowing(project_id, description, planted_chapter_id, "
                    "payoff_chapter_id, status, created_at) VALUES(?,?,?,?,?,?)",
                    (pid, desc, r["id"], r["id"], "paid", db.now()),
                )
        else:
            exist = db.query_one(
                "SELECT id FROM foreshadowing WHERE project_id=? AND description=?",
                (pid, desc),
            )
            if not exist:
                db.execute(
                    "INSERT INTO foreshadowing(project_id, description, planted_chapter_id, "
                    "status, created_at) VALUES(?,?,?,?,?)",
                    (pid, desc, r["id"], "open", db.now()),
                )
    for ev in it.get("timeline") or []:
        if not isinstance(ev, dict):
            continue
        desc = (ev.get("description") or "").strip()
        if not desc:
            continue
        mx = db.query_one(
            "SELECT COALESCE(MAX(idx),-1) m FROM timeline_events WHERE project_id=?", (pid,)
        )["m"]
        db.execute(
            "INSERT INTO timeline_events(project_id, chapter_id, time_label, description, idx, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (pid, r["id"], ev.get("time_label") or "", desc, mx + 1, db.now()),
        )


def _batch_titles_label(chunk: list) -> str:
    names = [r["title"] for r in chunk[:3] if r.get("title")]
    if not names:
        return f"{len(chunk)} 章"
    label = "、".join(names)
    if len(chunk) > 3:
        label += f" 等 {len(chunk)} 章"
    return label


async def _stream_plot_batch(pid: int, chunk: list, chars_seen: dict, lock: asyncio.Lock):
    """流式解析一批关键章：推送思考/输出进度，最后 yield chapter 事件。"""
    label = _batch_titles_label(chunk)
    block = [f"【{r['title']}】\n{(r['content'] or '')[:FULL_CHAPTER_CAP]}" for r in chunk]
    messages = [
        {"role": "system", "content": prompts.PLOT_EXTRACT_SYSTEM},
        {"role": "user", "content": prompts.PLOT_EXTRACT_USER.format(chapters="\n\n".join(block))},
    ]
    yield {"type": "status", "message": f"深度解析：{label}"}
    raw = ""
    async for ev in _stream_llm_collect(messages, status_msg=f"解析 {label}…"):
        if ev.get("type") == "_end":
            raw = ev.get("raw") or ""
        elif ev.get("type") == "error":
            yield ev
            return
        else:
            yield ev
    data = extract_json(raw)
    items = []
    if isinstance(data, dict):
        items = data.get("chapters") or []
    elif isinstance(data, list):
        items = data
    by_title = {str(it.get("title") or "").strip(): it for it in items if isinstance(it, dict)}
    async with lock:
        for i, r in enumerate(chunk):
            it = by_title.get(r["title"]) or (items[i] if i < len(items) and isinstance(items[i], dict) else {})
            _apply_plot_item(pid, r, it, chars_seen)
            yield {"type": "chapter", "chapter_id": r["id"], "title": r["title"], "deep": True}


async def _run_plot_batches(pid: int, rows: list, chars_seen: dict, *, prog_label: str):
    """并行批次解析，合并各批次的流式思考/输出事件。"""
    if not rows:
        return
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(PLOT_CONCURRENCY)
    batches = [rows[i:i + PLOT_BATCH] for i in range(0, len(rows), PLOT_BATCH)]
    total = len(rows)
    queue: asyncio.Queue = asyncio.Queue()

    async def worker(chunk):
        async with sem:
            try:
                async for ev in _stream_plot_batch(pid, chunk, chars_seen, lock):
                    await queue.put(ev)
            except LLMError as e:
                await queue.put({"type": "error", "message": str(e)})
            finally:
                await queue.put({"type": "_batch_done", "count": len(chunk)})

    yield {
        "type": "status",
        "message": f"并行解析关键章（{len(batches)} 批，共 {total} 章）…",
    }
    tasks = [asyncio.create_task(worker(b)) for b in batches]
    done_n = 0
    pending = len(tasks)
    try:
        while pending > 0:
            ev = await queue.get()
            if ev.get("type") == "_batch_done":
                pending -= 1
                done_n += int(ev.get("count") or 0)
                prog = f"{prog_label} {done_n}/{total}"
                _mark_import_plot(pid, stage_message=prog, deep_done=done_n)
                yield {"type": "status", "message": prog}
                continue
            if ev.get("type") == "chapter":
                pass
            yield ev
            if ev.get("type") == "error":
                for t in tasks:
                    t.cancel()
                return
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)


def _volume_has_summary(vol_id: int) -> bool:
    row = db.query_one("SELECT summary FROM volumes WHERE id=?", (vol_id,))
    return bool(row and (row.get("summary") or "").strip())


def _mark_volume_progress(pid: int, *, index: int, total: int, title: str, message: str):
    _mark_import_plot(
        pid,
        summarize_stage="running",
        volume_index=index,
        volume_total=total,
        volume_title=title,
        stage_message=message,
    )


async def _summarize_volumes(pid: int, rows: list, key_ids: set):
    """逐卷归纳并推送 SSE；进度写入 import_plot 供轮询/断点续传。"""
    vols = db.query("SELECT id, title, summary FROM volumes WHERE project_id=? ORDER BY idx, id", (pid,))
    by_vol: dict = {}
    for r in rows:
        if r["id"] not in key_ids:
            continue
        ch = db.query_one("SELECT summary, brief FROM chapters WHERE id=?", (r["id"],))
        if not ch:
            continue
        line = (ch.get("summary") or ch.get("brief") or r["title"] or "").strip()
        if line:
            by_vol.setdefault(r["volume_id"], []).append(f"{r['title']}：{line[:80]}")
    todo = []
    skipped = 0
    for vol in vols:
        lines = by_vol.get(vol["id"])
        if not lines:
            continue
        if _volume_has_summary(vol["id"]):
            skipped += 1
            continue
        todo.append((vol, lines))
    total = len(todo)
    if not total:
        msg = "卷级归纳已完成" if skipped else "无需卷级归纳（无深度章摘要）"
        _mark_import_plot(pid, summarize_stage="done", stage_message=msg)
        yield {"type": "status", "message": msg}
        return
    intro = f"共 {total} 卷待归纳"
    if skipped:
        intro += f"（已跳过 {skipped} 卷）"
    intro += "，每卷约 1～3 分钟…"
    _mark_volume_progress(pid, index=0, total=total, title="", message=intro)
    yield {"type": "status", "message": intro}
    done = 0
    for vol, lines in todo:
        done += 1
        title = vol["title"] or f"第{done}卷"
        msg = f"卷级归纳 {done}/{total}：{title}（{len(lines)} 章摘要）"
        _mark_volume_progress(pid, index=done, total=total, title=title, message=msg)
        yield {
            "type": "volume",
            "stage": "start",
            "volume_id": vol["id"],
            "title": title,
            "index": done,
            "total": total,
        }
        yield {"type": "status", "message": msg}
        messages = [
            {"role": "system", "content": prompts.VOLUME_SUMMARY_SYSTEM},
            {"role": "user", "content": prompts.VOLUME_SUMMARY_USER.format(
                title=title, summaries="\n".join(lines[:24]))},
        ]
        raw = ""
        failed = False
        async for ev in _stream_llm_collect(messages, status_msg=f"归纳《{title}》主线…"):
            if ev.get("type") == "_end":
                raw = ev.get("raw") or ""
            elif ev.get("type") == "error":
                failed = True
                yield ev
                break
            else:
                yield ev
        if failed:
            yield {"type": "status", "message": f"卷 {title} 归纳失败，已跳过"}
            continue
        data = extract_json(raw)
        summary = ""
        if isinstance(data, dict):
            summary = (data.get("summary") or "")[:500]
            if summary:
                db.execute(
                    "UPDATE volumes SET summary=? WHERE id=? AND project_id=?",
                    (summary, vol["id"], pid),
                )
        done_msg = f"已完成 {done}/{total} 卷：{title}"
        _mark_volume_progress(pid, index=done, total=total, title=title, message=done_msg)
        yield {
            "type": "volume",
            "stage": "done",
            "volume_id": vol["id"],
            "title": title,
            "index": done,
            "total": total,
            "summary": summary[:80] if summary else "",
        }
        yield {"type": "status", "message": done_msg}
    final = f"卷级归纳完成（{done}/{total} 卷）"
    _mark_import_plot(pid, summarize_stage="done", stage_message=final)
    yield {"type": "status", "message": final}


def _pending_deep_rows(pid: int) -> list:
    return db.query(
        "SELECT c.id, c.title, c.idx, c.volume_id, v.content FROM chapters c "
        "LEFT JOIN chapter_versions v ON v.id=c.current_version_id "
        "WHERE c.project_id=? AND (c.summary IS NULL OR c.summary='') "
        "ORDER BY c.volume_id, c.idx", (pid,))


def _chapter_has_summary(ch_id: int) -> bool:
    ch = db.query_one("SELECT summary FROM chapters WHERE id=?", (ch_id,))
    return bool(ch and (ch.get("summary") or "").strip())


def _project_title(pid: int) -> str:
    row = db.query_one("SELECT title FROM projects WHERE id=?", (pid,))
    return (row["title"] if row else "") or "导入作品"


def save_import_session(pid: int, title: str, status: str):
    db.execute(
        "INSERT INTO config(key, value) VALUES('import_session', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps({"pid": pid, "title": title, "status": status, "at": db.now()},
                    ensure_ascii=False),),
    )


def clear_import_session():
    db.execute("DELETE FROM config WHERE key='import_session'")


def get_import_session() -> dict:
    raw = db.query_one("SELECT value FROM config WHERE key='import_session'")
    data = db.jload(raw["value"] if raw else None, {}) or {}
    pid = data.get("pid")
    if not pid:
        return {}
    st = import_analysis_status(int(pid))
    if not st:
        return {}
    return {**data, **st, "title": _project_title(int(pid))}


def import_analysis_status(pid: int) -> dict | None:
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        return None
    row = db.query_one("SELECT brief FROM projects WHERE id=?", (pid,))
    brief = db.jload(row["brief"] if row else "{}", {}) or {}
    if brief.get("source") != "imported":
        return None
    plot = brief.get("import_plot") or {}
    rows = _chapter_rows(pid)
    deep_ratio = _project_deep_ratio(pid)
    key_ids = _select_key_chapters(rows, deep_ratio)
    deep_done = sum(1 for r in rows if r["id"] in key_ids and _chapter_has_summary(r["id"]))
    pending = sum(1 for r in rows if r["id"] in key_ids and not _chapter_has_summary(r["id"]))
    status = plot.get("status") or ("partial" if plot.get("partial") else "unknown")
    summarize_stage = plot.get("summarize_stage") or ""
    volume_total = int(plot.get("volume_total") or 0)
    volume_index = int(plot.get("volume_index") or 0)
    volume_title = plot.get("volume_title") or ""
    stage_message = plot.get("stage_message") or ""
    if (
        pending == 0
        and deep_done >= len(key_ids)
        and summarize_stage != "done"
        and status in ("partial", "done")
        and any(x in stage_message for x in ("卷级归纳已完成", "无需卷级归纳", "卷级归纳完成"))
    ):
        _mark_import_plot(pid, summarize_stage="done")
        summarize_stage = "done"
    needs_volume_resume = (
        summarize_stage == "running"
        or (
            pending == 0
            and deep_done >= len(key_ids)
            and summarize_stage != "done"
            and status in ("analyzing", "interrupted", "unknown")
        )
    )
    if pending == 0 and summarize_stage == "done":
        needs_resume = False
    else:
        needs_resume = (pending > 0 or needs_volume_resume) and status not in ("done", "full")
    needs_deep = bool(plot.get("partial")) and pending == 0 and status != "full"
    return {
        "pid": pid,
        "status": status,
        "total": len(rows),
        "deep": len(key_ids),
        "deep_done": deep_done,
        "pending": pending,
        "partial": bool(plot.get("partial")),
        "needs_resume": needs_resume,
        "needs_deep": needs_deep,
        "deep_ratio": deep_ratio if deep_ratio is not None else plot.get("deep_ratio"),
        "summarize_stage": summarize_stage,
        "volume_total": volume_total,
        "volume_index": volume_index,
        "volume_title": volume_title,
        "stage_message": stage_message,
    }


def _mark_import_plot(pid: int, **fields):
    row = db.query_one("SELECT brief FROM projects WHERE id=?", (pid,))
    brief = db.jload(row["brief"] if row else "{}", {}) or {}
    plot = brief.get("import_plot") or {}
    plot.update(fields)
    _merge_brief(pid, {"import_plot": plot})


async def _run_key_batches(pid: int, key_rows: list, chars_seen: dict):
    """并行解析关键章，yield SSE 事件（含思考/输出流）。"""
    async for ev in _run_plot_batches(pid, key_rows, chars_seen, prog_label="关键章进度"):
        yield ev


async def analyze_plot(pid: int, *, mode: str = "smart", deep_ratio: int = 10):
    """智能剧情解析：关键章并行深度抽取 + 其余占位 + 卷级归纳。"""
    rows = _chapter_rows(pid)
    if not rows:
        yield {"type": "result", "chapters": 0, "characters": 0, "partial": False}
        return
    deep_ratio = normalize_deep_ratio(deep_ratio) or 10
    title = _project_title(pid)
    save_import_session(pid, title, "analyzing")
    _mark_import_plot(pid, status="analyzing", deep_ratio=deep_ratio)
    yield {"type": "phase", "phase": "拆解剧情 / 流程图数据"}
    key_ids = _select_key_chapters(rows, deep_ratio)
    key_rows = [r for r in rows if r["id"] in key_ids]
    light_rows = [r for r in rows if r["id"] not in key_ids]
    for r in light_rows:
        _apply_light_chapter(r)
    if light_rows:
        yield {
            "type": "status",
            "message": f"已占位 {len(light_rows)} 章（可立即阅读），深度解析 {len(key_rows)} 章（{deep_ratio}%）…",
        }
    elif deep_ratio >= 100:
        yield {"type": "status", "message": f"全书 {len(key_rows)} 章深度解析…"}
    chars_seen = {r["name"]: True for r in db.query(
        "SELECT name FROM characters WHERE project_id=?", (pid,))}
    try:
        async for ev in _run_key_batches(pid, key_rows, chars_seen):
            yield ev
    except LLMError as e:
        _mark_import_plot(pid, status="interrupted")
        save_import_session(pid, title, "interrupted")
        yield {"type": "error", "message": str(e)}
        return

    yield {"type": "phase", "phase": "卷级剧情归纳"}
    async for ev in _summarize_volumes(pid, rows, key_ids):
        yield ev

    partial = len(light_rows) > 0
    status = "partial" if partial else "done"
    _mark_import_plot(
        pid,
        mode=mode,
        deep_ratio=deep_ratio,
        total=len(rows),
        deep=len(key_rows),
        light=len(light_rows),
        partial=partial,
        status=status,
        summarize_stage="done",
    )
    save_import_session(pid, title, status)
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
    yield {
        "type": "result",
        "chapters": len(rows),
        "characters": len(chars_seen),
        "deep": len(key_rows),
        "light": len(light_rows),
        "partial": partial,
        "deep_ratio": deep_ratio,
    }


async def analyze_plot_resume(pid: int):
    """断点续传：仅解析尚未完成的关键章，跳过已完成的文风/章节。"""
    rows = _chapter_rows(pid)
    if not rows:
        yield {"type": "result", "chapters": 0, "characters": 0, "partial": False}
        return
    title = _project_title(pid)
    save_import_session(pid, title, "analyzing")
    deep_ratio = _project_deep_ratio(pid)
    _mark_import_plot(pid, status="analyzing")
    key_ids = _select_key_chapters(rows, deep_ratio)
    pending = [r for r in rows if r["id"] in key_ids and not _chapter_has_summary(r["id"])]
    if not pending:
        yield {"type": "status", "message": "关键章已全部解析，正在检查卷级归纳…"}
    else:
        yield {"type": "phase", "phase": "继续拆解剧情"}
        yield {"type": "status", "message": f"续传：剩余 {len(pending)} 个关键章…"}
        chars_seen = {r["name"]: True for r in db.query(
            "SELECT name FROM characters WHERE project_id=?", (pid,))}
        try:
            async for ev in _run_key_batches(pid, pending, chars_seen):
                yield ev
        except LLMError as e:
            _mark_import_plot(pid, status="interrupted")
            save_import_session(pid, title, "interrupted")
            yield {"type": "error", "message": str(e)}
            return

    yield {"type": "phase", "phase": "卷级剧情归纳"}
    async for ev in _summarize_volumes(pid, rows, key_ids):
        yield ev

    light = sum(1 for r in rows if r["id"] not in key_ids)
    partial = light > 0
    status = "partial" if partial else "done"
    plot_fields = {
        "mode": "smart",
        "total": len(rows),
        "deep": len(key_ids),
        "light": light,
        "partial": partial,
        "status": status,
        "summarize_stage": "done",
    }
    if deep_ratio is not None:
        plot_fields["deep_ratio"] = deep_ratio
    _mark_import_plot(pid, **plot_fields)
    save_import_session(pid, title, status)
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
    yield {
        "type": "result",
        "chapters": len(rows),
        "characters": len(db.query("SELECT id FROM characters WHERE project_id=?", (pid,))),
        "deep": len(key_ids),
        "light": light,
        "partial": partial,
        "deep_ratio": deep_ratio,
    }


async def analyze_plot_deep(pid: int):
    """补全剩余章节的深度剧情解析（全书精细模式）。"""
    rows = _pending_deep_rows(pid)
    if not rows:
        yield {"type": "result", "chapters": 0, "characters": 0, "partial": False}
        return
    yield {"type": "phase", "phase": "深度补全剩余章节"}
    yield {"type": "status", "message": f"待深度解析 {len(rows)} 章…"}
    chars_seen = {r["name"]: True for r in db.query(
        "SELECT name FROM characters WHERE project_id=?", (pid,))}
    async for ev in _run_plot_batches(pid, rows, chars_seen, prog_label="深度补全"):
        if ev.get("type") == "error":
            yield ev
            return
        yield ev

    total = db.query_one("SELECT COUNT(*) AS n FROM chapters WHERE project_id=?", (pid,))["n"]
    title = _project_title(pid)
    _merge_brief(pid, {
        "import_plot": {
            "mode": "full", "total": total, "deep": total, "light": 0,
            "partial": False, "status": "full",
        },
    })
    save_import_session(pid, title, "full")
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
    yield {"type": "result", "chapters": total, "characters": len(chars_seen), "partial": False, "deep": total, "light": 0}


def create_imitate_project(src_pid: int, title: str, premise: str) -> int:
    """仿写建书：仅继承文风与章节数量骨架，不复制原书人物/世界观/剧情。"""
    src = db.query_one("SELECT * FROM projects WHERE id=?", (src_pid,))
    if not src:
        raise ValueError("源作品不存在")
    src_brief = db.jload(src.get("brief"), {}) or {}
    if not isinstance(src_brief, dict):
        src_brief = {}
    src_title = src["title"]
    story_premise = (premise or "").strip() or f"原创故事，仅借鉴《{src_title}》的叙事文风与节奏"
    new_brief = {
        "source": "imitated",
        "imitate": True,
        "source_project_id": src_pid,
        "source_title": src_title,
        "style_profile": src_brief.get("style_profile") or {},
        "style": src.get("style") or src_brief.get("style") or "",
        "pov": src_brief.get("pov", ""),
        "pacing": src_brief.get("pacing", ""),
        "tone": src_brief.get("tone", ""),
        "chapter_words": src_brief.get("chapter_words") or 2500,
        "logline": story_premise,
        "core_conflict": story_premise,
        "references": f"文风参考：《{src_title}》（禁止复用其人名、情节、专有名词）",
        "taboos": f"禁止出现《{src_title}》中的任何人名、地名、势力、道具、情节桥段与原文句子",
        "must_have": "全新原创人物、全新故事线；只模仿句式、节奏、对话密度与修辞习惯",
        "creation_notes": (
            f"【仿写项目·作者意图】\n"
            f"- 参考书《{src_title}》仅用于文风对标，不提供任何剧情、人物、设定素材。\n"
            f"- 新书核心创意：{story_premise}\n"
            f"- 章节序号只表示篇幅与更新节奏，**不代表**原书对应章节发生了什么。\n"
            f"- 每章须推进上述新故事：冲突、人物关系、秘密揭示；禁止把原书情节换名重写。\n"
            f"- 人物以系统生成的原创角色卡为准；临时路人须有原创姓名，禁止参考书名。\n"
            f"- 若梗概为空：根据前文 + 蓝图 + 人物卡续写，不要臆测原书剧情。"
        ),
    }
    new_title = (title or "").strip() or f"{src_title}·仿写"
    now = db.now()
    volumes = db.query("SELECT * FROM volumes WHERE project_id=? ORDER BY idx", (src_pid,))
    chapter_rows = []
    for vol in volumes:
        n = db.query_one(
            "SELECT COUNT(*) AS n FROM chapters WHERE project_id=? AND volume_id=?",
            (src_pid, vol["id"]),
        )["n"]
        chapter_rows.append((vol, n))

    with db.transaction() as tx:
        pid = tx.execute(
            "INSERT INTO projects(title, genre, premise, style, target_words, brief, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (new_title, src.get("genre") or "", story_premise,
             src.get("style") or "", src.get("target_words") or 200000,
             json.dumps(new_brief, ensure_ascii=False), now, now),
        )
        tx.execute(
            "INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?)",
            (pid, "[]", now),
        )
        all_chapters = []
        for vol, ch_count in chapter_rows:
            vol_title = vol["title"] if len(chapter_rows) > 1 else "正文"
            vid = tx.execute(
                "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
                (pid, vol["idx"], vol_title, ""),
            )
            for idx in range(1, ch_count + 1):
                all_chapters.append(
                    (pid, vid, idx, f"第{idx}章", "", "", "todo", 0, now, now),
                )
        if all_chapters:
            tx.executemany(
                "INSERT INTO chapters(project_id, volume_id, idx, title, brief, summary, "
                "status, book_done, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                all_chapters,
            )
    return pid


def _persist_imitate_characters(pid: int, data) -> int:
    if not isinstance(data, list):
        return 0
    now = db.now()
    n = 0
    for c in data[:8]:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        profile = {
            k: (c.get(k) or "")
            for k in ("appearance", "personality", "goal", "secret", "relationships", "speech_style")
        }
        db.execute(
            "INSERT INTO characters(project_id, name, role, profile, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (pid, name, (c.get("role") or "").strip(), json.dumps(profile, ensure_ascii=False), now, now),
        )
        n += 1
    return n


async def bootstrap_imitate_characters_stream(pid: int, premise: str, genre: str, source_title: str):
    """流式生成原创角色卡，推送思考/输出进度。"""
    yield {"type": "status", "message": "正在设计原创角色阵容…"}
    messages = [
        {"role": "system", "content": prompts.IMITATE_CHARACTERS_SYSTEM},
        {"role": "user", "content": prompts.IMITATE_CHARACTERS_USER.format(
            premise=premise or "（作者未填，请自行构思全新故事）",
            genre=genre or "未指定",
            source_title=source_title,
        )},
    ]
    raw = ""
    async for ev in _stream_llm_collect(messages, status_msg="设计原创角色…"):
        if ev.get("type") == "_end":
            raw = ev.get("raw") or ""
        elif ev.get("type") == "error":
            yield ev
            return
        elif ev.get("type") == "progress":
            chars = int(ev.get("chars") or 0)
            ratio = min(1.0, chars / 5000)
            yield {**ev, "pct": 40 + int(45 * ratio)}
        else:
            yield ev
    data = extract_json(raw)
    n = _persist_imitate_characters(pid, data)
    yield {"type": "characters", "count": n}
    yield {"type": "status", "message": f"已写入 {n} 个原创角色"}
    yield {"type": "progress", "pct": 85, "hint": f"角色设计完成（{n} 人）"}


async def bootstrap_imitate_characters(pid: int, premise: str, genre: str, source_title: str) -> int:
    """为仿写项目生成原创角色卡（不复用参考书人名）。"""
    n = 0
    async for ev in bootstrap_imitate_characters_stream(pid, premise, genre, source_title):
        if ev.get("type") == "characters":
            n = int(ev.get("count") or 0)
        elif ev.get("type") == "error":
            raise LLMError(ev.get("message") or "角色生成失败")
    return n


async def run_imitate_setup(
    src_pid: int,
    title: str,
    premise: str,
    *,
    bootstrap: bool = True,
    start_book: bool = True,
    mode: str = "draft_only",
    rounds=None,
    stop_on_error: bool = False,
):
    """仿写全流程 SSE：建书骨架 → 原创角色 → 启动整本创作。"""
    from .book import start as book_start

    src = db.query_one("SELECT * FROM projects WHERE id=?", (src_pid,))
    if not src:
        yield {"type": "error", "message": "源作品不存在"}
        return
    src_brief = db.jload(src.get("brief"), {}) or {}
    if not isinstance(src_brief, dict):
        src_brief = {}
    src_title = src["title"]
    story_premise = (premise or "").strip() or f"原创故事，仅借鉴《{src_title}》的叙事文风与节奏"
    new_brief = {
        "source": "imitated",
        "imitate": True,
        "source_project_id": src_pid,
        "source_title": src_title,
        "style_profile": src_brief.get("style_profile") or {},
        "style": src.get("style") or src_brief.get("style") or "",
        "pov": src_brief.get("pov", ""),
        "pacing": src_brief.get("pacing", ""),
        "tone": src_brief.get("tone", ""),
        "chapter_words": src_brief.get("chapter_words") or 2500,
        "logline": story_premise,
        "core_conflict": story_premise,
        "references": f"文风参考：《{src_title}》（禁止复用其人名、情节、专有名词）",
        "taboos": f"禁止出现《{src_title}》中的任何人名、地名、势力、道具、情节桥段与原文句子",
        "must_have": "全新原创人物、全新故事线；只模仿句式、节奏、对话密度与修辞习惯",
        "creation_notes": (
            f"【仿写项目·作者意图】\n"
            f"- 参考书《{src_title}》仅用于文风对标，不提供任何剧情、人物、设定素材。\n"
            f"- 新书核心创意：{story_premise}\n"
            f"- 章节序号只表示篇幅与更新节奏，**不代表**原书对应章节发生了什么。\n"
            f"- 每章须推进上述新故事：冲突、人物关系、秘密揭示；禁止把原书情节换名重写。\n"
            f"- 人物以系统生成的原创角色卡为准；临时路人须有原创姓名，禁止参考书名。\n"
            f"- 若梗概为空：根据前文 + 蓝图 + 人物卡续写，不要臆测原书剧情。"
        ),
    }
    new_title = (title or "").strip() or f"{src_title}·仿写"
    volumes = db.query("SELECT * FROM volumes WHERE project_id=? ORDER BY idx", (src_pid,))
    chapter_rows = []
    total_ch = 0
    for vol in volumes:
        n = db.query_one(
            "SELECT COUNT(*) AS n FROM chapters WHERE project_id=? AND volume_id=?",
            (src_pid, vol["id"]),
        )["n"]
        chapter_rows.append((vol, n))
        total_ch += n

    yield {"type": "phase", "phase": "创建仿写项目"}
    yield {"type": "progress", "pct": 2, "hint": "正在创建项目…"}
    now = db.now()
    pid = db.execute(
        "INSERT INTO projects(title, genre, premise, style, target_words, brief, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (new_title, src.get("genre") or "", story_premise,
         src.get("style") or "", src.get("target_words") or 200000,
         json.dumps(new_brief, ensure_ascii=False), now, now),
    )
    db.execute("INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?)", (pid, "[]", now))
    yield {"type": "status", "message": f"已创建《{new_title}》"}
    yield {"type": "progress", "pct": 8, "hint": f"共 {total_ch} 章待建立骨架"}

    inserted = 0
    batch_size = 250
    pending = []
    for vol, ch_count in chapter_rows:
        vol_title = vol["title"] if len(chapter_rows) > 1 else "正文"
        vid = db.execute(
            "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
            (pid, vol["idx"], vol_title, ""),
        )
        for idx in range(1, ch_count + 1):
            pending.append((pid, vid, idx, f"第{idx}章", "", "", "todo", 0, now, now))
            if len(pending) >= batch_size:
                db.executemany(
                    "INSERT INTO chapters(project_id, volume_id, idx, title, brief, summary, "
                    "status, book_done, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    pending,
                )
                inserted += len(pending)
                pending = []
                pct = 8 + int(32 * inserted / max(total_ch, 1))
                yield {
                    "type": "progress",
                    "pct": pct,
                    "hint": f"建立章节骨架 {inserted}/{total_ch}",
                }
    if pending:
        db.executemany(
            "INSERT INTO chapters(project_id, volume_id, idx, title, brief, summary, "
            "status, book_done, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            pending,
        )
        inserted += len(pending)
    yield {"type": "progress", "pct": 40, "hint": f"章节骨架完成（{inserted} 章）"}
    yield {"type": "status", "message": f"章节骨架 {inserted} 章"}

    characters = 0
    if bootstrap:
        yield {"type": "phase", "phase": "生成原创角色"}
        async for ev in bootstrap_imitate_characters_stream(
            pid, story_premise, src.get("genre") or "", src_title,
        ):
            if ev.get("type") == "characters":
                characters = int(ev.get("count") or 0)
            elif ev.get("type") == "error":
                yield ev
                return
            else:
                yield ev

    book = {"ok": True, "skipped": True}
    if start_book:
        yield {"type": "phase", "phase": "启动整本创作"}
        yield {"type": "progress", "pct": 90, "hint": "正在启动写作任务…"}
        try:
            book = book_start(pid, mode=mode, rounds=rounds, stop_on_error=stop_on_error)
        except RuntimeError as e:
            book = {"ok": False, "error": str(e)}
        if book.get("ok"):
            yield {
                "type": "status",
                "message": f"已开始整本创作（待写 {book.get('remaining', '?')} 章）",
            }
        else:
            yield {"type": "status", "message": book.get("error") or "未能自动开写"}

    yield {"type": "progress", "pct": 100, "hint": "仿写准备完成"}
    yield {
        "type": "done",
        "id": pid,
        "characters": characters,
        "chapters": inserted,
        "book": book,
    }
