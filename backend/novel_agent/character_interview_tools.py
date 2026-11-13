"""角色设计访谈可用工具。"""
from . import tools as book_tools
from .mcp import manager as mcp_manager

DIMENSIONS = [
    "主角身份", "主角性格", "主角目标", "主角弱点/秘密", "主角成长弧",
    "对手/反派", "感情线", "导师/盟友", "功能配角",
    "人物关系网", "阵营对立", "角色人数与偏好", "禁忌/不要的类型",
]


def collect_character_interview_tools():
    tools = [
        book_tools._fn(
            "list_character_dimensions",
            "列出角色设计访谈应覆盖的全部维度。规划提问前可先调用。",
        ),
        book_tools._fn(
            "analyze_character_coverage",
            "根据当前访谈记录，分析角色维度已覆盖与仍缺失的部分。",
            {"notes": {"type": "string", "description": "你对当前访谈进展的简要判断"}},
            [],
        ),
    ]
    handlers = {
        "list_character_dimensions": lambda _args: (
            "角色设计维度清单：\n" + "\n".join(f"- {d}" for d in DIMENSIONS)
        ),
        "analyze_character_coverage": lambda args: (
            f"（分析提示）{args.get('notes') or '请结合访谈记录判断 covered/missing 字段。'}"
        ),
    }

    for conn in mcp_manager.connected():
        for t in conn.tools[:20]:
            tool_name = f"mcp__{book_tools._sanitize(conn.name)}__{t['name']}"
            schema = dict(t["inputSchema"] or {})
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"[MCP:{conn.name}] {t['description'][:300]}",
                    "parameters": schema,
                },
            })
            handlers[tool_name] = book_tools._make_mcp_handler(conn, t["name"])

    return tools, handlers
