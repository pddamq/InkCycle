"""分支剧情：复制整本书为新项目。"""
import json

from . import db


def fork_project(project_id: int, branch_name: str, note: str = "") -> dict:
    from .backup import export_project_backup, import_project_backup

    data = export_project_backup(project_id)
    new_id = import_project_backup(data, title_suffix="")
    parent = db.query_one("SELECT title FROM projects WHERE id=?", (project_id,))
    db.execute(
        "UPDATE projects SET parent_project_id=?, branch_name=?, title=? WHERE id=?",
        (project_id, branch_name, f"{parent['title']} · {branch_name}", new_id),
    )
    db.execute(
        "INSERT INTO project_branches(project_id, parent_project_id, branch_name, note, created_at)"
        " VALUES(?,?,?,?,?)",
        (new_id, project_id, branch_name, note, db.now()),
    )
    brief = db.jload(db.query_one("SELECT brief FROM projects WHERE id=?", (new_id,))["brief"], {}) or {}
    brief["branch"] = {"from": project_id, "name": branch_name, "note": note}
    db.execute("UPDATE projects SET brief=? WHERE id=?", (json.dumps(brief, ensure_ascii=False), new_id))
    return {"project_id": new_id, "parent_project_id": project_id, "branch_name": branch_name}


def list_branches(project_id: int) -> list[dict]:
    rows = db.query(
        """SELECT p.id, p.title, p.branch_name, p.created_at, b.note, b.parent_project_id
           FROM project_branches b
           JOIN projects p ON p.id=b.project_id
           WHERE b.parent_project_id=? OR b.project_id=?
           ORDER BY b.created_at DESC""",
        (project_id, project_id),
    )
    root = db.query_one("SELECT id, title, parent_project_id, branch_name FROM projects WHERE id=?", (project_id,))
    return {"root": root, "branches": rows}
