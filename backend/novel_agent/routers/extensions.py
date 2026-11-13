"""扩展中心：Skills 管理 / MCP 服务器管理 / 全局配置。"""
import json
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from .. import db
from ..skills import (SkillError, install_from_folder, install_from_zip,
                      install_from_github, list_skills, toggle, uninstall,
                      get_skill_content, rescan)
from ..mcp import manager, MCPError

router = APIRouter(prefix="/api", tags=["extensions"])


# ---------------------------------------------------------------- Skills

@router.get("/skills")
def get_skills():
    return list_skills()


@router.post("/skills/rescan")
def rescan_skills():
    rescan()
    return {"ok": True, "skills": list_skills()}


@router.post("/skills/install")
def install_skill(body: dict):
    source = body.get("source")
    try:
        if source == "folder":
            skill = install_from_folder(body.get("path", ""))
        elif source == "github":
            skill = install_from_github(body.get("url", ""))
        else:
            raise SkillError("source 须为 folder 或 github")
    except SkillError as e:
        raise HTTPException(400, str(e))
    return skill


@router.post("/skills/install_zip")
async def install_skill_zip(file: UploadFile = File(...)):
    suffix = Path(file.filename or "skill.zip").suffix.lower() or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        skill = install_from_zip(tmp_path)
    except SkillError as e:
        raise HTTPException(400, str(e))
    finally:
        tmp_path.unlink(missing_ok=True)
    return skill


@router.get("/skills/{sid}")
def skill_detail(sid: int):
    content = get_skill_content(sid)
    if not content:
        raise HTTPException(404, "技能不存在或内容缺失")
    return content


@router.post("/skills/{sid}/toggle")
def skill_toggle(sid: int, body: dict):
    if not toggle(sid, bool(body.get("enabled"))):
        raise HTTPException(404, "技能不存在")
    return {"ok": True}


@router.delete("/skills/{sid}")
def skill_delete(sid: int):
    if not uninstall(sid):
        raise HTTPException(404, "技能不存在")
    return {"ok": True}


# ---------------------------------------------------------------- MCP

def _row(mid: int) -> dict:
    row = db.query_one("SELECT * FROM mcp_servers WHERE id=?", (mid,))
    if not row:
        raise HTTPException(404, "MCP 服务器不存在")
    return row


@router.get("/mcp/servers")
def mcp_list():
    rows = db.query("SELECT * FROM mcp_servers ORDER BY id")
    statuses = manager.statuses()
    out = []
    for r in rows:
        args = db.jload(r["args"], [])
        st = statuses.get(r["id"], {"status": "disconnected", "tools": 0, "error": "",
                                    "connected_at": ""})
        tools = []
        conn = manager.get(r["id"])
        if conn and conn.status == "connected":
            tools = [{"name": t["name"], "description": t["description"][:200],
                      "inputSchema": t["inputSchema"]} for t in conn.tools]
        out.append({
            "id": r["id"], "name": r["name"], "transport": r["transport"],
            "command": r["command"], "args": args, "url": r["url"],
            "enabled": bool(r["enabled"]), "auto_connect": bool(r["auto_connect"]),
            "status": st["status"], "error": st["error"],
            "connected_at": st.get("connected_at", ""), "tools": tools,
        })
    return out


@router.post("/mcp/servers")
def mcp_create(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    transport = body.get("transport", "stdio")
    if transport not in ("stdio", "http"):
        raise HTTPException(400, "transport 须为 stdio 或 http")
    if transport == "stdio" and not (body.get("command") or "").strip():
        raise HTTPException(400, "stdio 传输需要填写启动命令")
    if transport == "http" and not (body.get("url") or "").strip():
        raise HTTPException(400, "http 传输需要填写 URL")
    existing = db.query_one("SELECT id FROM mcp_servers WHERE name=?", (name,))
    if existing:
        raise HTTPException(400, f"已存在同名服务器：{name}")
    args = body.get("args") or []
    if isinstance(args, str):
        args = [a.strip() for a in args.splitlines() if a.strip()]
    mid = db.execute(
        "INSERT INTO mcp_servers(name, transport, command, args, url, enabled, auto_connect, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (name, transport, body.get("command", ""), json.dumps(args, ensure_ascii=False),
         body.get("url", ""), 1 if body.get("enabled", True) else 0,
         1 if body.get("auto_connect", True) else 0, db.now()),
    )
    return {"id": mid}


@router.put("/mcp/servers/{mid}")
def mcp_update(mid: int, body: dict):
    row = _row(mid)
    sets, args = [], []
    if "name" in body:
        sets.append("name=?")
        args.append(body["name"])
    if "transport" in body:
        sets.append("transport=?")
        args.append(body["transport"])
    if "command" in body:
        sets.append("command=?")
        args.append(body["command"])
    if "args" in body:
        a = body["args"] or []
        if isinstance(a, str):
            a = [x.strip() for x in a.splitlines() if x.strip()]
        sets.append("args=?")
        args.append(json.dumps(a, ensure_ascii=False))
    if "url" in body:
        sets.append("url=?")
        args.append(body["url"])
    if "enabled" in body:
        sets.append("enabled=?")
        args.append(1 if body["enabled"] else 0)
    if "auto_connect" in body:
        sets.append("auto_connect=?")
        args.append(1 if body["auto_connect"] else 0)
    if sets:
        args.append(mid)
        db.execute(f"UPDATE mcp_servers SET {', '.join(sets)} WHERE id=?", tuple(args))
    return {"ok": True}


@router.delete("/mcp/servers/{mid}")
async def mcp_delete(mid: int):
    _row(mid)
    await manager.disconnect(mid)
    db.execute("DELETE FROM mcp_servers WHERE id=?", (mid,))
    return {"ok": True}


@router.post("/mcp/servers/{mid}/connect")
async def mcp_connect(mid: int):
    row = _row(mid)
    try:
        tools = await manager.connect(row)
    except MCPError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "tools": [
        {"name": t["name"], "description": t["description"][:200]} for t in tools]}


@router.post("/mcp/servers/{mid}/disconnect")
async def mcp_disconnect(mid: int):
    _row(mid)
    await manager.disconnect(mid)
    return {"ok": True}


@router.post("/mcp/servers/{mid}/tools/{tool_name}/invoke")
async def mcp_invoke(mid: int, tool_name: str, body: dict):
    row = _row(mid)
    conn = manager.get(mid)
    if not conn or conn.status != "connected":
        raise HTTPException(400, "服务器未连接")
    args = body.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            raise HTTPException(400, "args 须为合法 JSON")
    try:
        result = await conn.call_tool(tool_name, args)
    except MCPError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": result}
