"""导入书籍：预览拆章、落库、文风/剧情分析、一键仿写。"""
import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import db, importer
from ..llm import LLMError

router = APIRouter(tags=["import"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_pack(agen):
    async def gen():
        try:
            async for ev in agen:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers=dict(SSE_HEADERS))


@router.post("/api/import/preview")
def preview_text(body: dict = None):
    body = body or {}
    text = body.get("text") or ""
    if not text.strip():
        raise HTTPException(400, "正文为空")
    return importer.split_book(text, body.get("filename") or "")


@router.post("/api/import/preview-file")
async def preview_file(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    text = importer.decode_bytes(data)
    return importer.split_book(text, file.filename or "")


@router.post("/api/import/commit")
def commit_import(body: dict = None):
    body = body or {}
    volumes = body.get("volumes") or []
    if not volumes:
        raise HTTPException(400, "没有可导入的章节")
    title = (body.get("title") or "").strip() or "导入作品"
    pid = importer.persist_import(
        title, body.get("genre") or "", volumes, body.get("filename") or "",
    )
    return {"id": pid}


@router.get("/api/import/session")
def import_session():
    """最近一次导入分析会话（用于书架「继续分析」）。"""
    return importer.get_import_session()


@router.get("/api/projects/{pid}/import/status")
def import_status(pid: int):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        raise HTTPException(404, "项目不存在")
    st = importer.import_analysis_status(pid)
    if not st:
        raise HTTPException(404, "非导入作品或无分析状态")
    return st


@router.post("/api/projects/{pid}/import/analyze")
async def analyze_import(pid: int, body: dict = None):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        raise HTTPException(404, "项目不存在")
    body = body or {}
    resume = bool(body.get("resume"))

    async def gen():
        try:
            result = {"chapters": 0, "characters": 0}
            async for ev in importer.analyze_style(pid, skip_if_done=resume):
                if ev.get("type") != "_end":
                    yield ev
            if resume:
                plot_iter = importer.analyze_plot_resume(pid)
            else:
                deep_ratio = importer.normalize_deep_ratio(body.get("deep_ratio"))
                if deep_ratio is None:
                    deep_ratio = 10
                plot_iter = importer.analyze_plot(pid, deep_ratio=deep_ratio)
            async for ev in plot_iter:
                if ev.get("type") == "result":
                    result = {k: ev[k] for k in ev if k != "type"}
                elif ev.get("type") != "_end":
                    yield ev
            yield {"type": "done", **result}
        except LLMError as e:
            yield {"type": "error", "message": str(e)}

    return _sse_pack(gen())


@router.post("/api/projects/{pid}/import/analyze-deep")
async def analyze_import_deep(pid: int):
    """补全导入后尚未深度解析的章节（可选，耗时长）。"""
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        raise HTTPException(404, "项目不存在")

    async def gen():
        try:
            result = {"chapters": 0, "characters": 0}
            async for ev in importer.analyze_plot_deep(pid):
                if ev.get("type") == "result":
                    result = {k: ev[k] for k in ev if k != "type"}
                elif ev.get("type") != "_end":
                    yield ev
            yield {"type": "done", **result}
        except LLMError as e:
            yield {"type": "error", "message": str(e)}

    return _sse_pack(gen())


@router.post("/api/projects/{pid}/imitate")
async def imitate_project(pid: int, body: dict = None):
    body = body or {}
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        raise HTTPException(404, "项目不存在")

    async def gen():
        try:
            async for ev in importer.run_imitate_setup(
                pid,
                body.get("title") or "",
                (body.get("premise") or "").strip(),
                bootstrap=bool(body.get("bootstrap_characters", True)),
                start_book=bool(body.get("start", True)),
                mode=body.get("mode", "draft_only"),
                rounds=body.get("rounds"),
                stop_on_error=bool(body.get("stop_on_error")),
            ):
                if ev.get("type") != "_end":
                    yield ev
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
        except ValueError as e:
            yield {"type": "error", "message": str(e)}
        except Exception as e:
            yield {"type": "error", "message": f"仿写失败：{e}"}

    return _sse_pack(gen())
