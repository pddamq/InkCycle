"""导出：TXT / Markdown，整本 / 单卷 / 单章。"""
import urllib.parse

from . import db


def _chapters_of(pid, volume_id=None):
    if volume_id:
        return db.query(
            "SELECT * FROM chapters WHERE project_id=? AND volume_id=? "
            "AND current_version_id IS NOT NULL ORDER BY idx",
            (pid, volume_id),
        )
    return db.query(
        "SELECT * FROM chapters WHERE project_id=? AND current_version_id IS NOT NULL "
        "ORDER BY volume_id, idx",
        (pid,),
    )


def _content_of(chapter):
    if not chapter.get("current_version_id"):
        return ""
    ver = db.query_one(
        "SELECT content FROM chapter_versions WHERE id=?", (chapter["current_version_id"],)
    )
    return ver["content"] if ver else ""


def _fmt(md, level, text):
    return f"{'#' * level} {text}\n\n" if md else f"{text}\n\n"


def build_export(pid, fmt="md", scope="book", scope_id=None) -> "tuple[str, str]":
    """返回 (文件名, 全文)。scope: book | volume | chapter"""
    project = db.query_one("SELECT * FROM projects WHERE id=?", (pid,))
    if not project:
        return ("error.txt", "项目不存在")
    md = fmt == "md"
    parts = []

    if scope == "chapter" and scope_id:
        ch = db.query_one("SELECT * FROM chapters WHERE id=? AND project_id=?", (scope_id, pid))
        if not ch or not ch["current_version_id"]:
            return (f"{project['title']}.txt", "该章节暂无正文")
        parts.append(_fmt(md, 1, f"{project['title']} · {ch['title']}"))
        parts.append(_content_of(ch).strip() + "\n")
        fname = f"{project['title']}_{ch['title']}.{fmt}"
        return (fname, "".join(parts))

    if scope == "volume" and scope_id:
        vol = db.query_one("SELECT * FROM volumes WHERE id=? AND project_id=?", (scope_id, pid))
        chapters = _chapters_of(pid, scope_id)
        title = vol["title"] if vol else "卷"
    else:
        vol = None
        chapters = _chapters_of(pid)

    if scope == "book":
        parts.append(_fmt(md, 1, project["title"]))
        if project["genre"] or project["premise"]:
            meta = f"类型：{project['genre'] or '未指定'}"
            if project["premise"]:
                meta += f" ｜ {project['premise']}"
            parts.append((f"> {meta}\n\n" if md else f"{meta}\n\n"))
        vols = db.query("SELECT * FROM volumes WHERE project_id=? ORDER BY idx", (pid,))
        by_vol = {}
        for ch in chapters:
            by_vol.setdefault(ch["volume_id"], []).append(ch)
        for v in vols:
            vch = by_vol.get(v["id"])
            if not vch:
                continue
            if len(vols) > 1 or v["title"] != "正文":
                parts.append(_fmt(md, 1, v["title"]))
            for ch in vch:
                parts.append(_fmt(md, 2, ch["title"]))
                parts.append(_content_of(ch).strip() + "\n\n")
        fname = f"{project['title']}.{fmt}"
    else:
        if vol and vol["title"] != "正文":
            parts.append(_fmt(md, 1, vol["title"]))
        for ch in chapters:
            parts.append(_fmt(md, 2, ch["title"]))
            parts.append(_content_of(ch).strip() + "\n\n")
        fname = f"{project['title']}_{vol['title'] if vol else '卷'}.{fmt}"

    return (fname, "".join(parts))


def download_headers(fname: str, fmt: str) -> dict:
    quoted = urllib.parse.quote(fname)
    ctype = "text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8"
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        "Cache-Control": "no-cache",
    }
