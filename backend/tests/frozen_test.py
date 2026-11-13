# -*- coding: utf-8 -*-
"""针对 frozen EXE 的快速全链路验证。需 EXE 已配置 API Key 或设置 NOVEL_AGENT_API_KEY。"""
import json
import sys

import httpx

from test_util import ensure_llm_ready

sys.stdout.reconfigure(encoding="utf-8")
PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
c = httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=120)
ok = 0
bad = 0


def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  [PASS] {name} {extra}")
    else:
        bad += 1
        print(f"  [FAIL] {name} {extra}")


def sse(url, body=None):
    evs = []
    with c.stream("POST", url, json=body or {}) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                evs.append(json.loads(line[5:]))
    return evs


ensure_llm_ready(c, PORT)

pid = c.post("/api/projects", json={"title": "冻结测试书", "genre": "玄幻",
             "premise": "测试 frozen exe 全链路", "target_words": 50000}).json()["id"]
check("创建项目", pid > 0, f"id={pid}")

evs = sse(f"/api/projects/{pid}/wizard/settings")
check("向导·设定", evs[-1]["type"] == "done")
evs = sse(f"/api/projects/{pid}/wizard/characters")
check("向导·角色", evs[-1]["type"] == "done")
evs = sse(f"/api/projects/{pid}/wizard/outline")
check("向导·大纲", evs[-1]["type"] == "done")

outline = c.get(f"/api/projects/{pid}/outline").json()
chid = outline[0]["chapters"][0]["id"]
evs = sse(f"/api/projects/{pid}/chapters/{chid}/auto", {"rounds": 2, "mode": "full"})
final = [e for e in evs if e["type"] == "done"][-1]
check("Agent 自动全流程", final.get("final_score", 0) >= 85, f"score={final.get('final_score')}")

r = c.get(f"/api/projects/{pid}/export?format=txt&scope=book")
check("导出", r.status_code == 200 and len(r.text) > 100, f"{len(r.text)}字")

print(f"\n结果: {ok} 通过 / {bad} 失败")
sys.exit(1 if bad else 0)
