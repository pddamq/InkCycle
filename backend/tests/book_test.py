# -*- coding: utf-8 -*-
"""整本自动创作端到端测试。需后端运行在 8765，且已配置 API Key 或 stub 服务器。"""
import json
import sys
import time

import httpx

from test_util import ensure_llm_ready

sys.stdout.reconfigure(encoding="utf-8")
PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
c = httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=180)
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def sse(url, body=None):
    evs = []
    with c.stream("POST", url, json=body or {}) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                evs.append(json.loads(line[5:]))
    return evs


def wait_done(pid, timeout=150):
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout:
        last = c.get(f"/api/projects/{pid}/book/status").json()
        if last["status"] in ("done", "stopped", "error"):
            return last
        time.sleep(1)
    return last


def main():
    ensure_llm_ready(c, PORT)
    print("== 准备：建项目 + 向导 ==")
    pid = c.post("/api/projects", json={"title": "整本测试书", "genre": "玄幻",
                 "premise": "测试整本自动创作", "target_words": 30000}).json()["id"]
    for step in ("settings", "characters", "outline"):
        sse(f"/api/projects/{pid}/wizard/{step}")
    outline = c.get(f"/api/projects/{pid}/outline").json()
    total_ch = sum(len(v["chapters"]) for v in outline)
    check("大纲已生成", total_ch > 0, f"{total_ch} 章")

    print("== 启动整本创作 ==")
    st = c.get(f"/api/projects/{pid}/book/status").json()
    check("初始状态 idle/done", st["status"] in ("idle", "stopped", "done"), st["status"])
    check("剩余=总章数", st["remaining"] == total_ch, f"{st['remaining']}/{st['total']}")

    r = c.post(f"/api/projects/{pid}/book/start", json={"mode": "full", "rounds": 2}).json()
    check("启动成功", r.get("ok"), str(r))

    # 重复启动应被拒绝
    r2 = c.post(f"/api/projects/{pid}/book/start", json={}).json()
    check("运行中拒绝重复启动", r2.get("ok") is False, r2.get("error", ""))

    print("== 等待完成 ==")
    final = wait_done(pid)
    check("任务完成", final["status"] == "done", f"status={final['status']} done={final['done']}/{final['total']}")
    check("所有章节已完成", final["done"] == final["total"] == total_ch)

    # 校验每章都产出了正文且 book_done=1
    outline2 = c.get(f"/api/projects/{pid}/outline").json()
    with_content = sum(1 for v in outline2 for ch in v["chapters"] if ch["has_content"])
    check("每章都有正文", with_content == total_ch, f"{with_content}/{total_ch}")

    print("== 事件日志 ==")
    evs = c.get(f"/api/projects/{pid}/book/events?since=0").json()["events"]
    types = [e["type"] for e in evs]
    check("有 job_start", "job_start" in types)
    check("有 job_done", "job_done" in types)
    check("chapter_done 数=章数", types.count("chapter_done") == total_ch, str(types.count("chapter_done")))
    check("有评分事件", "review" in types)

    print("== 完成后再启动应拒绝 ==")
    r3 = c.post(f"/api/projects/{pid}/book/start", json={}).json()
    check("全部完成后拒绝", r3.get("ok") is False and "完成" in r3.get("error", ""), r3.get("error", ""))

    print("== 续跑：新增一章后只补跑该章 ==")
    vid = outline2[0]["id"]
    c.post(f"/api/projects/{pid}/chapters", json={"volume_id": vid, "title": "补写章", "brief": "补充一段过渡情节"})
    st2 = c.get(f"/api/projects/{pid}/book/status").json()
    check("新增章后 remaining=1", st2["remaining"] == 1, f"remaining={st2['remaining']} total={st2['total']}")
    r4 = c.post(f"/api/projects/{pid}/book/start", json={"mode": "full", "rounds": 1}).json()
    check("续跑启动成功且只跑1章", r4.get("ok") and r4.get("remaining") == 1, str(r4))
    final2 = wait_done(pid)
    check("续跑完成 done==total", final2["status"] == "done" and final2["done"] == final2["total"],
          f"{final2['done']}/{final2['total']}")

    print("== SSE 流回放 ==")
    got = {"state": False, "job_done": False, "end": False}
    with c.stream("GET", f"/api/projects/{pid}/book/stream?since=0") as resp:
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if ev.get("type") == "state":
                got["state"] = True
            elif ev.get("type") == "job_done":
                got["job_done"] = True
            elif ev.get("type") == "stream_end":
                got["end"] = True
                break
    check("SSE 发送 state", got["state"])
    check("SSE 回放 job_done", got["job_done"])
    check("SSE 正常结束", got["end"])

    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
