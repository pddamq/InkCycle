"""FastAPI 应用主入口：路由注册、前端静态托管（SPA fallback）、启动初始化。"""
import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .paths import resource_dir
from .routers import (
    projects, agent_api, extensions, config_api, book_api,
    interview_api, import_api, meta_api, character_interview_api,
)

app = FastAPI(title="小说创作 Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(agent_api.router)
app.include_router(extensions.router)
app.include_router(config_api.router)
app.include_router(book_api.router)
app.include_router(interview_api.router)
app.include_router(import_api.router)
app.include_router(meta_api.router)
app.include_router(character_interview_api.router)


@app.on_event("startup")
async def on_startup():
    db.init_db()
    from .skills import rescan
    rescan()
    from .mcp import manager

    # 进程重启后，内存中的整本创作任务已不存在：把遗留的 running/stopping 标记为 stopped（可续跑）
    db.execute("UPDATE book_jobs SET status='stopped' WHERE status IN ('running','stopping')")

    async def auto_connect():
        for row in db.query("SELECT * FROM mcp_servers WHERE enabled=1 AND auto_connect=1"):
            try:
                await manager.connect(row)
            except Exception:
                pass  # 状态记录在连接对象上，UI 可见错误

    asyncio.get_event_loop().create_task(auto_connect())


@app.get("/api/health")
def health():
    return {"ok": True, "app": "novel-agent"}


# ---------------------------------------------------------------- 前端静态托管

_DIST = resource_dir()

if _DIST.exists():
    assets = _DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if full_path and not full_path.endswith("/"):
            candidate = _DIST / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
        index = _DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"detail": "frontend not built"}, status_code=404)
