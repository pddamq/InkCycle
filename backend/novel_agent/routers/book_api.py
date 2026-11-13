"""整本自动创作的 HTTP 接口：启动 / 停止 / 状态 / 实时事件流。"""
import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .. import db
from ..book import manager, start, stop, get_status, recent_events, COARSE

router = APIRouter(prefix="/api/projects", tags=["book"])

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


@router.post("/{pid}/book/start")
async def book_start(pid: int, body: dict = None):
    body = body or {}
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        return {"ok": False, "error": "项目不存在"}
    return start(pid, mode=body.get("mode", "full"),
                 rounds=body.get("rounds"), stop_on_error=bool(body.get("stop_on_error")))


@router.post("/{pid}/book/stop")
async def book_stop(pid: int):
    return stop(pid)


@router.get("/{pid}/book/status")
async def book_status(pid: int):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (pid,)):
        return {"error": "项目不存在"}
    return get_status(pid)


@router.get("/{pid}/book/events")
async def book_events(pid: int, since: int = 0):
    """轮询式获取粗粒度事件（SSE 的降级方案）。"""
    return {"events": recent_events(pid, since), "status": get_status(pid)}


@router.get("/{pid}/book/stream")
async def book_stream(pid: int, since: int = 0):
    """SSE 实时流：先回放 seq>since 的历史粗粒度事件，再实时跟随。

    客户端断开重连时带上已收到的最大 seq 即可无缝续传。
    """
    async def gen():
        job = manager.get(pid)
        q: "asyncio.Queue" = asyncio.Queue()
        # 先订阅，避免回放与直播之间漏事件
        job.subscribers.add(q)
        last_seq = since
        try:
            yield _sse({"type": "state", **get_status(pid)})
            # 回放历史
            for ev in recent_events(pid, since):
                last_seq = max(last_seq, ev.get("seq", last_seq))
                yield _sse(ev)
            # 若没有活动任务，回放完即结束
            if not job.running:
                yield _sse({"type": "stream_end"})
                return
            # 实时跟随
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield _sse({"type": "ping"})  # 保活
                    if not job.running:
                        yield _sse({"type": "stream_end"})
                        return
                    continue
                seq = ev.get("seq")
                if seq is not None:
                    if seq <= last_seq:
                        continue  # 去重（回放已覆盖）
                    last_seq = seq
                yield _sse(ev)
                if ev.get("type") in ("job_done", "job_stopped", "job_error"):
                    yield _sse({"type": "state", **get_status(pid)})
                    break
        finally:
            job.subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=dict(SSE_HEADERS))
