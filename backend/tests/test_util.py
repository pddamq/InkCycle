# -*- coding: utf-8 -*-
"""HTTP 测试共用工具。"""
import json
import os
import sys


def ensure_llm_ready(client, port_hint=""):
    """确保被测服务可调用 LLM。"""
    cfg = client.get("/api/config").json()
    if cfg.get("has_key"):
        return
    key = os.environ.get("NOVEL_AGENT_API_KEY", "").strip()
    if key:
        client.put("/api/config", json={"api_key": key})
        return
    # stub 服务器：无 Key 也能响应访谈（SSE）
    evs = []
    with client.stream("POST", "/api/interview/next", json={"history": []}) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                evs.append(json.loads(line[5:]))
    probe = next((e for e in reversed(evs) if e.get("type") == "interview"), {})
    if probe.get("phase") in ("asking", "ready"):
        return
    print("未配置 LLM：请在设置页填入 API Key，或设置环境变量 NOVEL_AGENT_API_KEY")
    print("本地自动化测试可启动 stub 服务器：python run_stub_server.py")
    if port_hint:
        print(f"（当前端口 {port_hint}）")
    sys.exit(2)
