"""整本自动创作：后台任务编排。

逐章调用 agent.run_auto（起草→审校→修订循环），把整本书写完。
特点：
- 后台 asyncio 任务，不阻塞 HTTP；可在前端离开后继续跑。
- 进度持久化到 DB（book_jobs / book_job_events），断线/重启后可"继续"。
- 可续跑：只处理 book_done=0 的章节，已完成的自动跳过。
- 优雅停止：完成当前章后停，不丢已写内容。
- 实时事件：粗粒度事件入库（可回放），细粒度（正文增量）仅直播。
"""
import asyncio
import json

from . import db
from . import agent

# 入库（粗粒度）事件类型
COARSE = {
    "job_start", "chapter_start", "phase", "review",
    "chapter_done", "chapter_error", "job_done", "job_stopped", "job_error",
}


class BookJob:
    def __init__(self, pid: int):
        self.pid = pid
        self.task: "asyncio.Task | None" = None
        self.cancel = False
        self.subscribers: "set[asyncio.Queue]" = set()

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()


class BookManager:
    def __init__(self):
        self.jobs: "dict[int, BookJob]" = {}

    def get(self, pid: int) -> BookJob:
        if pid not in self.jobs:
            self.jobs[pid] = BookJob(pid)
        return self.jobs[pid]


manager = BookManager()


# ---------------------------------------------------------------- 事件分发

def _next_seq(pid: int) -> int:
    row = db.query_one("SELECT seq FROM book_jobs WHERE project_id=?", (pid,))
    seq = (row["seq"] if row else 0) + 1
    db.execute("UPDATE book_jobs SET seq=?, updated_at=? WHERE project_id=?",
               (seq, db.now(), pid))
    return seq


def _broadcast(job: BookJob, ev: dict):
    for q in list(job.subscribers):
        # 慢消费者保护：队列过长时丢弃细粒度事件
        if q.qsize() > 3000 and ev.get("type") not in COARSE:
            continue
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass


def emit_coarse(job: BookJob, type_: str, **payload):
    seq = _next_seq(job.pid)
    ev = {"seq": seq, "type": type_, **payload}
    db.execute(
        "INSERT INTO book_job_events(project_id, seq, type, payload, created_at) VALUES(?,?,?,?,?)",
        (job.pid, seq, type_, json.dumps(payload, ensure_ascii=False), db.now()))
    _broadcast(job, ev)


def emit_live(job: BookJob, type_: str, **payload):
    _broadcast(job, {"type": type_, **payload})


def _set_status(pid: int, status: str, **fields):
    sets = ["status=?", "updated_at=?"]
    args = [status, db.now()]
    for k, v in fields.items():
        sets.append(f"{k}=?")
        args.append(v)
    args.append(pid)
    db.execute(f"UPDATE book_jobs SET {', '.join(sets)} WHERE project_id=?", tuple(args))


# ---------------------------------------------------------------- 任务状态

def _ensure_row(pid: int):
    if not db.query_one("SELECT project_id FROM book_jobs WHERE project_id=?", (pid,)):
        cfg = db.get_config()
        db.execute(
            "INSERT INTO book_jobs(project_id, status, mode, rounds, threshold, started_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (pid, "idle", "full", db.cfg_int(cfg, "agent_rounds", 2),
             db.cfg_int(cfg, "review_threshold", 85), db.now(), db.now()))


def get_status(pid: int) -> dict:
    _ensure_row(pid)
    row = db.query_one("SELECT * FROM book_jobs WHERE project_id=?", (pid,))
    total = db.query_one("SELECT COUNT(*) n FROM chapters WHERE project_id=?", (pid,))["n"]
    done = db.query_one(
        "SELECT COUNT(*) n FROM chapters WHERE project_id=? AND book_done=1", (pid,))["n"]
    live = manager.get(pid).running
    status = row["status"]
    # DB 里是 running 但实际没有活动任务（如重启后）→ 视为已中断
    if status == "running" and not live:
        status = "interrupted"
    return {
        "status": status, "live": live, "mode": row["mode"], "rounds": row["rounds"],
        "threshold": row["threshold"], "stop_on_error": bool(row["stop_on_error"]),
        "total": total, "done": done, "remaining": max(0, total - done),
        "seq": row["seq"], "current_chapter_id": row["current_chapter_id"],
        "current_chapter_title": row["current_chapter_title"], "error": row["error"],
        "started_at": row["started_at"], "updated_at": row["updated_at"],
    }


def recent_events(pid: int, since: int = 0, limit: int = 500) -> list:
    rows = db.query(
        "SELECT seq, type, payload, created_at FROM book_job_events "
        "WHERE project_id=? AND seq>? ORDER BY seq LIMIT ?", (pid, since, limit))
    out = []
    for r in rows:
        out.append({"seq": r["seq"], "type": r["type"],
                    "created_at": r["created_at"], **db.jload(r["payload"], {})})
    return out


# ---------------------------------------------------------------- 启动 / 停止

def start(pid: int, mode: str = "full", rounds: int = None, stop_on_error: bool = False) -> dict:
    _ensure_row(pid)
    job = manager.get(pid)
    if job.running:
        return {"ok": False, "error": "该书已有正在进行的整本创作任务"}
    cfg = db.get_config()
    rounds = rounds or db.cfg_int(cfg, "agent_rounds", 2)
    threshold = db.cfg_int(cfg, "review_threshold", 85)
    total = db.query_one("SELECT COUNT(*) n FROM chapters WHERE project_id=?", (pid,))["n"]
    if total == 0:
        return {"ok": False, "error": "还没有章节，请先生成或添加大纲"}
    remaining = db.query_one(
        "SELECT COUNT(*) n FROM chapters WHERE project_id=? AND book_done=0", (pid,))["n"]
    if remaining == 0:
        return {"ok": False, "error": "所有章节都已完成，无需再跑"}

    job.cancel = False
    db.execute(
        "UPDATE book_jobs SET status='running', mode=?, rounds=?, threshold=?, stop_on_error=?, "
        "current_chapter_id=NULL, current_chapter_title='', error='', started_at=?, updated_at=? "
        "WHERE project_id=?",
        (mode, rounds, threshold, 1 if stop_on_error else 0, db.now(), db.now(), pid))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as e:
        return {"ok": False, "error": f"无法启动整本创作任务：{e}"}
    job.task = loop.create_task(_run_job(job, mode, rounds, threshold, stop_on_error))
    return {"ok": True, "remaining": remaining, "total": total}


def stop(pid: int) -> dict:
    job = manager.get(pid)
    if not job.running:
        return {"ok": False, "error": "没有正在运行的任务"}
    job.cancel = True
    _set_status(pid, "stopping")
    return {"ok": True, "message": "将在完成当前章后停止"}


# ---------------------------------------------------------------- 运行器

async def _run_job(job: BookJob, mode: str, rounds: int, threshold: int, stop_on_error: bool):
    pid = job.pid
    try:
        queue = db.query(
            "SELECT id, title FROM chapters WHERE project_id=? AND book_done=0 "
            "ORDER BY volume_id, idx", (pid,))
        total = db.query_one("SELECT COUNT(*) n FROM chapters WHERE project_id=?", (pid,))["n"]
        emit_coarse(job, "job_start", total=total, remaining=len(queue), mode=mode, rounds=rounds)

        done_count = total - len(queue)
        stopped = False
        for i, ch in enumerate(queue):
            if job.cancel:
                stopped = True
                break
            db.execute(
                "UPDATE book_jobs SET current_chapter_id=?, current_chapter_title=?, done=?, updated_at=? "
                "WHERE project_id=?",
                (ch["id"], ch["title"], done_count, db.now(), pid))
            emit_coarse(job, "chapter_start", chapter_id=ch["id"], title=ch["title"],
                        index=i + 1, remaining=len(queue) - i)

            final_score, err = await _run_chapter(job, ch, mode, rounds, threshold)

            if job.cancel:
                stopped = True
                break
            if err:
                emit_coarse(job, "chapter_error", chapter_id=ch["id"], title=ch["title"], message=err)
                if stop_on_error:
                    stopped = True
                    db.execute("UPDATE book_jobs SET error=? WHERE project_id=?", (err, pid))
                    break
                # 出错也标记为已处理，避免续跑时死循环
                db.execute("UPDATE chapters SET book_done=1 WHERE id=?", (ch["id"],))
            else:
                db.execute("UPDATE chapters SET book_done=1 WHERE id=?", (ch["id"],))
                emit_coarse(job, "chapter_done", chapter_id=ch["id"], title=ch["title"],
                            score=final_score, index=i + 1)
            done_count += 1

        unresolved = db.query_one(
            "SELECT COUNT(*) n FROM foreshadowing WHERE project_id=? AND status='open'", (pid,))["n"]
        if stopped:
            _set_status(pid, "stopped", done=done_count, current_chapter_id=None,
                        current_chapter_title="")
            emit_coarse(job, "job_stopped", done=done_count, total=total)
        else:
            _set_status(pid, "done", done=done_count, current_chapter_id=None,
                        current_chapter_title="")
            emit_coarse(job, "job_done", done=done_count, total=total, unresolved_foreshadow=unresolved)
    except asyncio.CancelledError:
        _set_status(pid, "stopped", current_chapter_id=None, current_chapter_title="")
        emit_coarse(job, "job_stopped", reason="cancelled")
    except Exception as e:  # noqa: BLE001
        _set_status(pid, "error", error=str(e), current_chapter_id=None, current_chapter_title="")
        emit_coarse(job, "job_error", message=str(e))
    finally:
        job.cancel = False


async def _run_chapter(job: BookJob, ch: dict, mode: str, rounds: int, threshold: int):
    """跑单章 agent 循环，转发事件；返回 (final_score, error)。"""
    pid, chid = job.pid, ch["id"]
    final_score, err = None, None
    try:
        async for ev in agent.run_auto(pid, chid, rounds=rounds, mode=mode):
            if job.cancel:
                break
            t = ev.get("type")
            if t == "delta":
                emit_live(job, "delta", chapter_id=chid, text=ev.get("text", ""))
            elif t == "reasoning":
                emit_live(job, "reasoning", chapter_id=chid, text=ev.get("text", ""))
            elif t == "status":
                emit_live(job, "status", chapter_id=chid, message=ev.get("message", ""))
            elif t in ("tool_call", "tool_result"):
                emit_live(job, t, chapter_id=chid, **{k: v for k, v in ev.items() if k != "type"})
            elif t == "phase":
                emit_coarse(job, "phase", chapter_id=chid, phase=ev.get("phase"), round=ev.get("round"))
            elif t == "review":
                emit_coarse(job, "review", chapter_id=chid, score=ev.get("score"),
                            issues=len(ev.get("issues") or []))
            elif t == "done" and ev.get("stage") == "auto":
                final_score = ev.get("final_score")
            elif t == "error":
                err = ev.get("message", "未知错误")
    except Exception as e:  # noqa: BLE001
        err = str(e)
    return final_score, err
