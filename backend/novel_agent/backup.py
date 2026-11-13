"""项目 / 全库备份与恢复。"""
import io
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

from . import db
from .paths import DATA_DIR

TABLES_PROJECT = [
    ("projects", "id"),
    ("world", "project_id"),
    ("characters", "project_id"),
    ("volumes", "project_id"),
    ("chapters", "project_id"),
    ("chapter_versions", None),
    ("reviews", None),
    ("foreshadowing", "project_id"),
    ("timeline_events", "project_id"),
    ("text_chunks", "project_id"),
    ("book_jobs", "project_id"),
    ("book_job_events", "project_id"),
    ("project_branches", "project_id"),
]


def export_full_backup() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if db.DB_PATH.is_file():
            zf.write(db.DB_PATH, "data.db")
        meta = {"version": 1, "type": "full", "exported_at": db.now()}
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    buf.seek(0)
    return buf.read()


def export_project_backup(project_id: int) -> bytes:
    project = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not project:
        raise ValueError("项目不存在")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        payload = {"project": project, "tables": {}}
        payload["tables"]["world"] = db.query("SELECT * FROM world WHERE project_id=?", (project_id,))
        payload["tables"]["characters"] = db.query("SELECT * FROM characters WHERE project_id=?", (project_id,))
        payload["tables"]["volumes"] = db.query("SELECT * FROM volumes WHERE project_id=?", (project_id,))
        chapters = db.query("SELECT * FROM chapters WHERE project_id=?", (project_id,))
        payload["tables"]["chapters"] = chapters
        ch_ids = [c["id"] for c in chapters]
        if ch_ids:
            ph = ",".join("?" * len(ch_ids))
            payload["tables"]["chapter_versions"] = db.query(
                f"SELECT * FROM chapter_versions WHERE chapter_id IN ({ph})", tuple(ch_ids))
            payload["tables"]["reviews"] = db.query(
                f"SELECT * FROM reviews WHERE chapter_id IN ({ph})", tuple(ch_ids))
        else:
            payload["tables"]["chapter_versions"] = []
            payload["tables"]["reviews"] = []
        payload["tables"]["foreshadowing"] = db.query(
            "SELECT * FROM foreshadowing WHERE project_id=?", (project_id,))
        payload["tables"]["timeline_events"] = db.query(
            "SELECT * FROM timeline_events WHERE project_id=?", (project_id,))
        payload["tables"]["text_chunks"] = db.query(
            "SELECT * FROM text_chunks WHERE project_id=?", (project_id,))
        payload["tables"]["book_jobs"] = db.query(
            "SELECT * FROM book_jobs WHERE project_id=?", (project_id,))
        payload["tables"]["book_job_events"] = db.query(
            "SELECT * FROM book_job_events WHERE project_id=?", (project_id,))
        payload["tables"]["project_branches"] = db.query(
            "SELECT * FROM project_branches WHERE project_id=? OR parent_project_id=?",
            (project_id, project_id))
        zf.writestr("project.json", json.dumps(payload, ensure_ascii=False))
        meta = {"version": 1, "type": "project", "project_id": project_id, "title": project["title"]}
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False))
    buf.seek(0)
    return buf.read()


def import_full_backup(data: bytes) -> None:
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "r") as zf:
        if "data.db" not in zf.namelist():
            raise ValueError("无效的备份：缺少 data.db")
        db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        backup = db.DB_PATH.with_suffix(".db.bak")
        if db.DB_PATH.is_file():
            shutil.copy2(db.DB_PATH, backup)
        with zf.open("data.db") as src, open(db.DB_PATH, "wb") as dst:
            shutil.copyfileobj(src, dst)
    db._conn = None  # force reconnect
    db.init_db()


def import_project_backup(data: bytes, title_suffix: str = "（恢复）") -> int:
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "r") as zf:
        if "project.json" not in zf.namelist():
            raise ValueError("无效的项目备份")
        payload = json.loads(zf.read("project.json").decode("utf-8"))
    proj = dict(payload["project"])
    old_pid = proj.get("id")
    proj.pop("id", None)
    base_title = proj.get("title") or "恢复的项目"
    proj["title"] = f"{base_title}{title_suffix}" if title_suffix else base_title
    proj["created_at"] = db.now()
    proj["updated_at"] = db.now()
    new_id = db.execute(
        "INSERT INTO projects(title, genre, premise, style, target_words, brief, status, parent_project_id, branch_name, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (proj.get("title", ""), proj.get("genre", ""), proj.get("premise", ""),
         proj.get("style", ""), proj.get("target_words", 200000), proj.get("brief", "{}"),
         proj.get("status", "active"), proj.get("parent_project_id"), proj.get("branch_name", ""),
         proj["created_at"], proj["updated_at"]),
    )
    tables = payload.get("tables", {})
    for row in tables.get("world", []):
        db.execute(
            "INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?)",
            (new_id, row.get("sections", "[]"), db.now()),
        )
    char_map = {}
    for row in tables.get("characters", []):
        nid = db.execute(
            "INSERT INTO characters(project_id, name, role, profile, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (new_id, row["name"], row.get("role", ""), row.get("profile", "{}"), db.now(), db.now()),
        )
        char_map[row["id"]] = nid
    vol_map = {}
    for row in tables.get("volumes", []):
        nid = db.execute(
            "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
            (new_id, row.get("idx", 0), row.get("title", ""), row.get("summary", "")),
        )
        vol_map[row["id"]] = nid
    default_vol = None
    if not vol_map and tables.get("chapters"):
        default_vol = db.execute(
            "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
            (new_id, 0, "正文", ""),
        )
    ch_map = {}
    for row in tables.get("chapters", []):
        vol_id = vol_map.get(row["volume_id"])
        if vol_id is None:
            vol_id = default_vol or (list(vol_map.values())[0] if vol_map else None)
        if vol_id is None:
            vol_id = db.execute(
                "INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
                (new_id, 0, "正文", ""),
            )
            default_vol = vol_id
        nid = db.execute(
            "INSERT INTO chapters(project_id, volume_id, idx, title, brief, status, summary, word_count, book_done, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (new_id, vol_id,
             row.get("idx", 0), row.get("title", ""), row.get("brief", ""), row.get("status", "todo"),
             row.get("summary", ""), row.get("word_count", 0), row.get("book_done", 0), db.now(), db.now()),
        )
        ch_map[row["id"]] = nid
    ver_map = {}
    for row in tables.get("chapter_versions", []):
        nid = db.execute(
            "INSERT INTO chapter_versions(chapter_id, vtype, content, word_count, review_id, note, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (ch_map.get(row["chapter_id"]), row.get("vtype", "manual"), row.get("content", ""),
             row.get("word_count", 0), row.get("review_id"), row.get("note", ""), row.get("created_at") or db.now()),
        )
        ver_map[row["id"]] = nid
    rev_map = {}
    for row in tables.get("reviews", []):
        nid = db.execute(
            "INSERT INTO reviews(chapter_id, version_id, round, score, report, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (ch_map.get(row["chapter_id"]), ver_map.get(row.get("version_id")),
             row.get("round", 1), row.get("score", 0), row.get("report", "{}"),
             row.get("created_at") or db.now()),
        )
        rev_map[row["id"]] = nid
    for row in tables.get("chapter_versions", []):
        new_vid = ver_map.get(row["id"])
        old_rid = row.get("review_id")
        if new_vid and old_rid and rev_map.get(old_rid):
            db.execute("UPDATE chapter_versions SET review_id=? WHERE id=?", (rev_map[old_rid], new_vid))
    for row in tables.get("chapters", []):
        if row.get("current_version_id") and row["id"] in ch_map:
            cv = ver_map.get(row["current_version_id"])
            if cv:
                db.execute("UPDATE chapters SET current_version_id=? WHERE id=?", (cv, ch_map[row["id"]]))
    for row in tables.get("foreshadowing", []):
        db.execute(
            "INSERT INTO foreshadowing(project_id, description, planted_chapter_id, status, payoff_chapter_id, note, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (new_id, row["description"], ch_map.get(row.get("planted_chapter_id")),
             row.get("status", "open"), ch_map.get(row.get("payoff_chapter_id")),
             row.get("note", ""), row.get("created_at") or db.now()),
        )
    for row in tables.get("timeline_events", []):
        db.execute(
            "INSERT INTO timeline_events(project_id, chapter_id, time_label, description, idx, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (new_id, ch_map.get(row.get("chapter_id")), row.get("time_label", ""),
             row["description"], row.get("idx", 0), row.get("created_at") or db.now()),
        )
    for row in tables.get("text_chunks", []):
        ref_type = row.get("ref_type", "chapter")
        ref_id = ch_map.get(row.get("ref_id")) if ref_type == "chapter" else row.get("ref_id")
        db.execute(
            "INSERT INTO text_chunks(project_id, chapter_id, ref_type, ref_id, title, chunk_idx, content, tfidf, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (new_id, ch_map.get(row.get("chapter_id")), ref_type,
             ref_id, row.get("title", ""), row.get("chunk_idx", 0),
             row.get("content", ""), row.get("tfidf", "{}"), row.get("updated_at") or db.now()),
        )
    for row in tables.get("book_jobs", []):
        status = row.get("status", "idle")
        if status in ("running", "stopping"):
            status = "stopped"
        db.execute(
            "INSERT INTO book_jobs(project_id, status, mode, rounds, threshold, stop_on_error, "
            "total, done, seq, current_chapter_id, current_chapter_title, error, started_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id, status, row.get("mode", "full"), row.get("rounds", 2), row.get("threshold", 85),
             row.get("stop_on_error", 0), row.get("total", 0), row.get("done", 0), row.get("seq", 0),
             ch_map.get(row.get("current_chapter_id")), row.get("current_chapter_title", ""),
             row.get("error", ""), row.get("started_at", ""), row.get("updated_at") or db.now()),
        )
    for row in tables.get("book_job_events", []):
        payload = db.jload(row.get("payload"), {})
        if isinstance(payload, dict) and payload.get("chapter_id") in ch_map:
            payload["chapter_id"] = ch_map[payload["chapter_id"]]
        db.execute(
            "INSERT INTO book_job_events(project_id, seq, type, payload, created_at) VALUES(?,?,?,?,?)",
            (new_id, row.get("seq", 0), row.get("type", ""),
             json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else (row.get("payload") or "{}"),
             row.get("created_at") or db.now()),
        )
    for row in tables.get("project_branches", []):
        if row.get("project_id") != old_pid:
            continue
        db.execute(
            "INSERT INTO project_branches(project_id, parent_project_id, branch_name, note, created_at)"
            " VALUES(?,?,?,?,?)",
            (new_id, row.get("parent_project_id"), row.get("branch_name", ""),
             row.get("note", ""), row.get("created_at") or db.now()),
        )
    return new_id
