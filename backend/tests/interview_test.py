# -*- coding: utf-8 -*-
"""开书访谈端到端测试。需后端运行在指定端口（默认 8765），且已配置 API Key 或 stub 服务器。"""
import json
import sys

import httpx

from test_util import ensure_llm_ready

sys.stdout.reconfigure(encoding="utf-8")
PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
c = httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=120)
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def sse_events(url, body=None):
    evs = []
    with c.stream("POST", url, json=body or {}) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                evs.append(json.loads(line[5:]))
    return evs


def interview_next(history):
    evs = sse_events("/api/interview/next", {"history": history})
    err = next((e for e in evs if e.get("type") == "error"), None)
    if err:
        return {"phase": "error", "error": err.get("message")}
    inv = next((e for e in reversed(evs) if e.get("type") == "interview"), None)
    return inv or {"phase": "error", "error": "未收到 interview 事件"}


def interview_compile(history):
    evs = sse_events("/api/interview/compile", {"history": history})
    err = next((e for e in evs if e.get("type") == "error"), None)
    if err:
        return {"ok": False, "error": err.get("message")}
    comp = next((e for e in reversed(evs) if e.get("type") == "compile"), None)
    return comp or {"ok": False, "error": "未收到 compile 事件"}


def main():
    ensure_llm_ready(c, PORT)
    history = []
    rounds = 0
    # 多轮访谈，直到 ready 或上限
    for _ in range(8):
        r = interview_next(history)
        if r.get("phase") == "error":
            check("访谈轮询", False, r.get("error"))
            break
        rounds += 1
        qs = r.get("questions", [])
        if r.get("intro"):
            history.append({"role": "ai", "content": r["intro"]})
        if qs:
            history.append({"role": "ai", "content": "；".join(q["text"] for q in qs)})
            # 模拟作者回答
            ans = "；".join(f"{q.get('label','')}: 测试回答关于{q.get('label','')}的内容" for q in qs)
            history.append({"role": "user", "content": ans})
        if r.get("phase") == "ready":
            check("访谈在合理轮次内 ready", 2 <= rounds <= 8, f"rounds={rounds}")
            check("ready 时覆盖维度非空", len(r.get("covered", [])) > 0, str(r.get("covered"))[:60])
            break
    else:
        check("访谈能达成 ready", False, "8 轮仍未 ready")

    # 汇编蓝图
    comp = interview_compile(history)
    check("compile 成功", comp.get("ok"), comp.get("error", ""))
    brief = comp.get("brief", {})
    check("蓝图含核心字段", all(k in brief for k in ("title", "genre", "logline", "theme", "protagonist")),
          str(sorted(brief.keys()))[:80])
    proj = comp.get("project", {})
    check("派生建项目字段", proj.get("title") and "brief" in proj, str({k: proj.get(k) for k in ("title","genre","target_words")}))

    # 用蓝图建项目，确认 brief 落库
    pid = c.post("/api/projects", json=proj).json()["id"]
    got = c.get(f"/api/projects/{pid}").json()
    check("项目存了蓝图", isinstance(got.get("brief"), dict) and got["brief"].get("logline"),
          str(got.get("brief", {}).get("title")))

    # 蓝图应驱动生成：跑设定/角色/大纲，确认成功
    def sse(url):
        evs = []
        with c.stream("POST", url, json={}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    evs.append(json.loads(line[5:]))
        return evs
    check("蓝图驱动·设定", sse(f"/api/projects/{pid}/wizard/settings")[-1]["type"] == "done")
    check("蓝图驱动·角色", sse(f"/api/projects/{pid}/wizard/characters")[-1]["type"] == "done")
    check("蓝图驱动·大纲", sse(f"/api/projects/{pid}/wizard/outline")[-1]["type"] == "done")

    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
