"""开书访谈可用工具（维度清单 + 已连接 MCP）。"""
import re

from . import tools as book_tools
from .mcp import manager as mcp_manager

DIMENSIONS = [
    "核心创意", "类型", "子类型/流派", "主题内核", "目标读者", "基调",
    "时代背景", "世界规则", "主要场景", "势力结构",
    "主角", "对手/反派", "配角与感情线", "人物关系",
    "核心冲突", "开篇钩子", "情节走向", "结局类型", "情绪与爽点",
    "视角人称", "文风", "节奏", "篇幅", "禁忌/雷点", "必须包含", "对标作品",
]


def collect_interview_tools():
    tools = [
        book_tools._fn(
            "list_interview_dimensions",
            "列出开书访谈应覆盖的全部维度，以及各维度的简要说明。规划下一轮提问前可先调用。",
        ),
        book_tools._fn(
            "analyze_coverage",
            "根据当前访谈记录，分析已覆盖与仍缺失的关键维度。",
            {"notes": {"type": "string", "description": "你对当前访谈进展的简要判断"}},
            [],
        ),
    ]
    handlers = {
        "list_interview_dimensions": lambda _args: (
            "开书访谈维度清单：\n" + "\n".join(f"- {d}" for d in DIMENSIONS)
        ),
        "analyze_coverage": lambda args: (
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
