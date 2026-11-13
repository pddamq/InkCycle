"""测试用 Mock MCP 服务器（stdio 传输）。

按行收发 JSON-RPC 2.0，提供一个 search_web 工具。
用法：python mock_mcp_server.py
"""
import json
import sys


def handle(method, params):
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-mcp", "version": "1.0.0"},
        }
    if method == "tools/list":
        return {"tools": [{
            "name": "search_web",
            "description": "搜索网络资料（演示），返回与关键词相关的资料摘要",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["keyword"],
            },
        }]}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "search_web":
            kw = args.get("keyword", "")
            return {"content": [{
                "type": "text",
                "text": f"【演示搜索结果】关于“{kw}”共找到 3 条资料：\n"
                        f"1. {kw}的起源可追溯至旧纪元，最早的记载刻在石碑背面。\n"
                        f"2. 民间传闻中，{kw}与一场未记录的火灾有关。\n"
                        f"3. 行会档案将其归类为“违规物品”，经手人签名被涂抹。",
            }]}
        return {"content": [{"type": "text", "text": f"未知工具：{name}"}], "isError": True}
    return None


def main():
    # MCP stdio 传输规范要求 UTF-8；Windows 下 Python 默认本地编码，需显式重配
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method", "")
        if method.startswith("notifications/"):
            continue
        result = handle(method, msg.get("params") or {})
        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
