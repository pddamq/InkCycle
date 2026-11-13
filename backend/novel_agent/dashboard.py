"""一致性看板 + 文风漂移检测。"""
import re

from . import db

LOW_SCORE = 75


def consistency_report(project_id: int) -> dict:
    project = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not project:
        return {"ok": False, "error": "项目不存在"}

    open_fs = db.query(
        """SELECT f.*, pc.title AS planted_title, pc.idx AS planted_idx
           FROM foreshadowing f
           LEFT JOIN chapters pc ON pc.id=f.planted_chapter_id
           WHERE f.project_id=? AND f.status='open'
           ORDER BY f.id""",
        (project_id,),
    )
    low_reviews = db.query(
        """SELECT r.score, r.round, r.created_at, c.id AS chapter_id, c.title, c.idx
           FROM reviews r
           JOIN chapters c ON c.id=r.chapter_id
           WHERE c.project_id=? AND r.score < ?
           ORDER BY r.score ASC, r.created_at DESC
           LIMIT 20""",
        (project_id, LOW_SCORE),
    )
    todo_chapters = db.query(
        """SELECT id, title, idx, status, word_count FROM chapters
           WHERE project_id=? AND status IN ('todo','drafted')
           ORDER BY volume_id, idx LIMIT 30""",
        (project_id,),
    )
    timeline_dup = _timeline_conflicts(project_id)
    style_drift = style_drift_report(project_id)

    return {
        "ok": True,
        "project_id": project_id,
        "title": project["title"],
        "open_foreshadowing": [
            {
                "id": f["id"],
                "description": f["description"],
                "planted_chapter_id": f.get("planted_chapter_id"),
                "planted_title": f.get("planted_title") or "未知章节",
            }
            for f in open_fs
        ],
        "low_score_chapters": low_reviews,
        "incomplete_chapters": todo_chapters,
        "timeline_issues": timeline_dup,
        "style_drift": style_drift,
        "summary": {
            "open_foreshadowing": len(open_fs),
            "low_score": len(low_reviews),
            "incomplete": len(todo_chapters),
            "timeline_issues": len(timeline_dup),
            "style_drift_high": sum(1 for x in style_drift.get("chapters", []) if x.get("drift") == "high"),
        },
    }


def _timeline_conflicts(project_id: int) -> list[dict]:
    events = db.query(
        "SELECT id, chapter_id, time_label, description FROM timeline_events WHERE project_id=? ORDER BY idx, id",
        (project_id,),
    )
    issues = []
    seen = {}
    for ev in events:
        label = (ev.get("time_label") or "").strip()
        if not label:
            continue
        if label in seen:
            issues.append({
                "time_label": label,
                "message": f"时间标签「{label}」重复出现，请核对时序",
                "events": [seen[label], ev["id"]],
            })
        else:
            seen[label] = ev["id"]
    return issues


def _style_profile(project: dict) -> dict:
    brief = db.jload(project.get("brief"), {}) or {}
    profile = brief.get("style_profile") or {}
    if profile:
        return profile
    return {
        "pov": project.get("style") or "",
        "tone": brief.get("tone") or "",
        "sentence": brief.get("style") or "",
    }


def _chapter_style_signals(text: str) -> dict:
    text = text or ""
    chars = len(re.sub(r"\s", "", text))
    if chars == 0:
        return {"chars": 0}
    dialog = len(re.findall(r"[「『""]", text))
    exclaim = text.count("！") + text.count("!")
    ellipsis = text.count("…") + text.count("...")
    avg_sent = 0
    sents = re.split(r"[。！？!?]", text)
    sents = [s for s in sents if s.strip()]
    if sents:
        avg_sent = sum(len(re.sub(r"\s", "", s)) for s in sents) / len(sents)
    return {
        "chars": chars,
        "dialog_ratio": round(dialog / max(chars / 200, 1), 3),
        "exclaim_ratio": round(exclaim / max(chars / 1000, 1), 3),
        "ellipsis_ratio": round(ellipsis / max(chars / 1000, 1), 3),
        "avg_sentence_len": round(avg_sent, 1),
    }


def style_drift_report(project_id: int) -> dict:
    project = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not project:
        return {"baseline": {}, "chapters": []}
    baseline = _style_profile(project)
    rows = db.query(
        """SELECT c.id, c.title, c.idx, v.content
           FROM chapters c
           JOIN chapter_versions v ON v.id=c.current_version_id
           WHERE c.project_id=?
           ORDER BY c.volume_id, c.idx""",
        (project_id,),
    )
    if not rows:
        return {"baseline": baseline, "chapters": []}

    ref = _chapter_style_signals(rows[0]["content"])
    out = []
    for row in rows:
        sig = _chapter_style_signals(row["content"])
        if sig.get("chars", 0) < 300:
            continue
        drift_score = 0
        if ref.get("avg_sentence_len") and sig.get("avg_sentence_len"):
            diff = abs(sig["avg_sentence_len"] - ref["avg_sentence_len"]) / max(ref["avg_sentence_len"], 1)
            drift_score += min(diff, 1) * 40
        if ref.get("dialog_ratio") is not None:
            drift_score += min(abs(sig["dialog_ratio"] - ref["dialog_ratio"]), 1) * 30
        level = "low"
        if drift_score >= 45:
            level = "high"
        elif drift_score >= 25:
            level = "medium"
        out.append({
            "chapter_id": row["id"],
            "title": row["title"],
            "idx": row["idx"],
            "drift": level,
            "score": round(drift_score, 1),
            "signals": sig,
        })
    return {"baseline": baseline, "chapters": out}
