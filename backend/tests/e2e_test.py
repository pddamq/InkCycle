# -*- coding: utf-8 -*-
"""端到端冒烟测试：向导 → 章节 → Agent 循环 → MCP 工具 → 导出。

需后端运行在 8765，且已配置 API Key，或先启动 stub 服务器：python run_stub_server.py
"""
import json
import sys

import httpx

from test_util import ensure_llm_ready

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8765"
c = httpx.Client(base_url=BASE, timeout=120)
PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def sse(method, url, body=None):
    events = []
    with c.stream(method, url, json=body or {}) as r:
        if r.status_code != 200:
            return [{"type": "error", "message": f"HTTP {r.status_code}"}]
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events


def main():
    ensure_llm_ready(c, "8765")
    print("== 基础 ==")
    check("health", c.get("/api/health").json()["ok"])
    skills = c.get("/api/skills").json()
    check("内置技能数量=3", len(skills) == 3, str([s["name"] for s in skills]))

    print("== 项目 ==")
    pid = c.post("/api/projects", json={
        "title": "雾都档案", "genre": "悬疑",
        "premise": "落魄侦探接到一桩三十年前的连环失踪案，所有线索都指向他自己缺失的记忆",
        "target_words": 200000,
    }).json()["id"]
    p = [x for x in c.get("/api/projects").json() if x["id"] == pid][0]
    check("项目创建（中文无损）", p["title"] == "雾都档案", p["title"])

    print("== 向导（mock SSE）==")
    evs = sse("POST", f"/api/projects/{pid}/wizard/settings")
    check("wizard/settings", evs[-1]["type"] == "done", f"sections={len(evs[-1].get('sections', []))}")
    evs = sse("POST", f"/api/projects/{pid}/wizard/characters")
    check("wizard/characters", evs[-1]["type"] == "done", f"count={evs[-1].get('count')}")
    chars = c.get(f"/api/projects/{pid}/characters").json()
    check("角色已入库", len(chars) == 4, str([x["name"] for x in chars]))
    evs = sse("POST", f"/api/projects/{pid}/wizard/outline")
    check("wizard/outline", evs[-1]["type"] == "done", str(evs[-1]))
    outline = c.get(f"/api/projects/{pid}/outline").json()
    n_ch = sum(len(v["chapters"]) for v in outline)
    check("大纲已入库", n_ch == 11, f"卷={len(outline)} 章={n_ch}")

    ch1 = outline[0]["chapters"][0]
    chid = ch1["id"]

    print("== Agent：初稿（含内置工具调用）==")
    evs = sse("POST", f"/api/projects/{pid}/chapters/{chid}/draft")
    types = [e["type"] for e in evs]
    deltas = "".join(e.get("text", "") for e in evs if e["type"] == "delta")
    check("draft 完成", evs[-1].get("type") == "done", evs[-1].get("word_count"))
    check("draft 流式增量", len(deltas) > 300, f"{len(deltas)}字")
    check("draft 触发工具调用", "tool_call" in types, str([e["name"] for e in evs if e["type"] == "tool_call"]))
    check("draft 工具有结果", any(e["type"] == "tool_result" for e in evs))
    check("draft 生成摘要", bool(c.get(f"/api/projects/{pid}/chapters/{chid}").json()["summary"]))

    print("== Agent：审校 ==")
    evs = sse("POST", f"/api/projects/{pid}/chapters/{chid}/review")
    rev = [e for e in evs if e["type"] == "review"]
    check("review 完成", evs[-1].get("type") == "done")
    check("review 结构化", rev and rev[0]["score"] > 0 and len(rev[0]["issues"]) >= 2,
          f"score={rev[0]['score'] if rev else '-'}")

    print("== Agent：自动循环（初稿→审校→修订→审校）==")
    evs = sse("POST", f"/api/projects/{pid}/chapters/{chid}/auto", {"rounds": 2, "mode": "full"})
    phases = [e["phase"] for e in evs if e["type"] == "phase"]
    final = [e for e in evs if e["type"] == "done"][-1]
    check("auto 完成", final.get("final_score", 0) >= 85, f"score={final.get('final_score')}")
    check("auto 阶段流", "draft" in phases and "review" in phases and "revise" in phases, str(phases))

    print("== 版本 ==")
    vs = c.get(f"/api/projects/{pid}/chapters/{chid}/versions").json()
    check("版本历史", len(vs) >= 3, f"{[v['vtype'] for v in vs]}")
    restore = c.post(f"/api/projects/{pid}/chapters/{chid}/versions/{vs[-1]['id']}/restore").json()
    check("版本回滚", restore.get("version_id"))
    ch = c.get(f"/api/projects/{pid}/chapters/{chid}").json()
    check("手动编辑保存版本", c.put(f"/api/projects/{pid}/chapters/{chid}", json={
        "content": ch["content"] + "\n（手动补记一句）"}).json().get("ok"))
    vs2 = c.get(f"/api/projects/{pid}/chapters/{chid}/versions").json()
    check("manual 版本入列", any(v["vtype"] == "manual" for v in vs2))

    print("== 伏笔 / 时间线 ==")
    fid = c.post(f"/api/projects/{pid}/foreshadow", json={
        "description": "铜牌上的裂痕来历", "planted_chapter_id": chid}).json()["id"]
    check("伏笔登记", c.get(f"/api/projects/{pid}/foreshadow").json()[0]["description"] == "铜牌上的裂痕来历")
    eid = c.post(f"/api/projects/{pid}/timeline", json={
        "time_label": "第1夜", "description": "当铺纵火，铜牌易主", "chapter_id": chid}).json()["id"]
    check("时间线登记", len(c.get(f"/api/projects/{pid}/timeline").json()) == 1)

    print("== Skills 安装 ==")
    check("toggle", c.post(f"/api/skills/{skills[0]['id']}/toggle", json={"enabled": False}).json()["ok"])
    check("toggle back", c.post(f"/api/skills/{skills[0]['id']}/toggle", json={"enabled": True}).json()["ok"])
    detail = c.get(f"/api/skills/{skills[0]['id']}").json()
    check("技能内容可读", "对话" in detail.get("content", ""), skills[0]["name"])

    print("== MCP ==")
    for s in c.get("/api/mcp/servers").json():  # 清理上次残留
        if s["name"] == "mock-tools":
            c.delete(f"/api/mcp/servers/{s['id']}")
    mid = c.post("/api/mcp/servers", json={
        "name": "mock-tools", "transport": "stdio",
        "command": r"c:\Users\coder\Desktop\aiagent\backend\.venv\Scripts\python.exe",
        "args": [r"c:\Users\coder\Desktop\aiagent\backend\tests\mock_mcp_server.py"],
        "enabled": True, "auto_connect": True}).json()["id"]
    conn = c.post(f"/api/mcp/servers/{mid}/connect").json()
    check("MCP 连接", conn.get("ok") and len(conn.get("tools", [])) == 1, str(conn)[:150])
    inv = c.post(f"/api/mcp/servers/{mid}/tools/search_web/invoke", json={"args": {"keyword": "铜牌"}}).json()
    check("MCP 工具手动调用", inv.get("ok") and "演示搜索结果" in inv.get("result", ""))

    # MCP 工具暴露给 Agent：起草第 2 章应出现 mcp__mock-tools__search_web
    ch2 = outline[0]["chapters"][1]["id"]
    evs = sse("POST", f"/api/projects/{pid}/chapters/{ch2}/draft")
    names = [e["name"] for e in evs if e["type"] == "tool_call"]
    check("Agent 调用 MCP 工具", any(n.startswith("mcp__") for n in names), str(names))

    print("== 导出 ==")
    r = c.get(f"/api/projects/{pid}/export?format=md&scope=book")
    check("整本导出 md", r.status_code == 200 and "雾都档案" in r.text, f"{len(r.text)}字")
    r = c.get(f"/api/projects/{pid}/export?format=txt&scope=chapter&scope_id={chid}")
    check("单章导出 txt", r.status_code == 200 and len(r.text) > 100)

    print("== 配置 ==")
    cfg = c.get("/api/config").json()
    check("配置可读", bool(cfg.get("base_url")))
    test_r = c.post("/api/config/test").json()
    check("test 连接", test_r.get("ok"), test_r.get("message", ""))
    models_r = c.post("/api/config/models").json()
    check("拉取模型", models_r.get("ok") and len(models_r.get("models", [])) > 0, str(models_r.get("models", [])[:3]))

    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
