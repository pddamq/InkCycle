"""项目备份恢复测试。"""
import json
import sys

from novel_agent import db
from novel_agent.backup import export_project_backup, import_project_backup


def test_book_jobs_restore():
    db.init_db()
    pid = db.execute(
        "INSERT INTO projects(title, created_at, updated_at) VALUES(?,?,?)",
        ("book-job-test", db.now(), db.now()),
    )
    vid = db.execute(
        "INSERT INTO volumes(project_id, idx, title) VALUES(?,?,?)", (pid, 0, "V1"))
    cid = db.execute(
        "INSERT INTO chapters(project_id, volume_id, idx, title, book_done, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (pid, vid, 0, "C1", 1, db.now(), db.now()),
    )
    db.execute(
        "INSERT INTO book_jobs(project_id, status, mode, rounds, threshold, total, done, seq, "
        "current_chapter_id, current_chapter_title, started_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "running", "full", 2, 85, 10, 3, 5, cid, "C1", db.now(), db.now()),
    )
    db.execute(
        "INSERT INTO book_job_events(project_id, seq, type, payload, created_at) VALUES(?,?,?,?,?)",
        (pid, 1, "chapter_start", json.dumps({"chapter_id": cid, "title": "C1"}), db.now()),
    )
    data = export_project_backup(pid)
    new_id = import_project_backup(data)
    job = db.query_one("SELECT * FROM book_jobs WHERE project_id=?", (new_id,))
    ev = db.query_one("SELECT payload FROM book_job_events WHERE project_id=?", (new_id,))
    new_cid = db.query_one("SELECT id FROM chapters WHERE project_id=?", (new_id,))["id"]
    assert job["status"] == "stopped", job["status"]
    assert job["done"] == 3
    assert job["current_chapter_id"] == new_cid
    assert json.loads(ev["payload"])["chapter_id"] == new_cid
    print("OK book_jobs restore", new_id)


if __name__ == "__main__":
    try:
        test_book_jobs_restore()
    except AssertionError as e:
        print("FAIL", e)
        sys.exit(1)
