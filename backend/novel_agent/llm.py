"""LLM 客户端：OpenAI 兼容 /chat/completions，流式 + 工具调用。

stream_chat 产出事件：
  {"type": "text", "text": "..."}            增量正文
  {"type": "reasoning", "text": "..."}        思考/推理增量（若模型支持）
  {"type": "tool_call_delta", ...}           工具调用参数流式片段
  {"type": "tool_calls", "calls": [...]}      模型请求调用工具（一轮结束）
chat() 返回完整文本。
"""
import json
import re

import httpx

from .db import get_config, cfg_int, cfg_float

_PROGRESS_FIELD = re.compile(
    r'"(?:name|title|style_summary|summary)"\s*:\s*"((?:[^"\\]|\\.){1,48})"'
)


class LLMError(Exception):
    pass


def _require_key(cfg: dict):
    if not cfg.get("api_key"):
        raise LLMError("未配置 API Key，请先在「设置」中填入 OpenAI 兼容接口的 Key")


def _auth_headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        h["Authorization"] = f"Bearer {cfg['api_key']}"
    return h


def _endpoint(cfg: dict) -> str:
    return cfg["base_url"].rstrip("/") + "/chat/completions"


def _models_endpoint(cfg: dict) -> str:
    return cfg["base_url"].rstrip("/") + "/models"


def _parse_models_payload(data) -> list[str]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data") or data.get("models") or []
    else:
        items = []
    ids: list[str] = []
    for item in items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            mid = item.get("id") or item.get("name") or item.get("model")
            if mid:
                ids.append(str(mid))
    seen: set[str] = set()
    out: list[str] = []
    for mid in ids:
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    return sorted(out, key=str.lower)


async def fetch_models(cfg: dict = None) -> list[str]:
    """拉取 OpenAI 兼容 GET /models 列表。"""
    cfg = cfg or get_config()
    _require_key(cfg)
    timeout = httpx.Timeout(connect=15, read=30, write=30, pool=30)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(_models_endpoint(cfg), headers=_auth_headers(cfg))
            if resp.status_code != 200:
                body = resp.text[:500]
                raise LLMError(f"API 返回 {resp.status_code}: {body}")
            return _parse_models_payload(resp.json())
    except httpx.HTTPError as e:
        raise LLMError(f"网络错误：{e}") from e


def stream_progress_hint(text: str) -> str:
    """从流式 JSON 片段提取可读进度（角色名、章节名等）。"""
    names = []
    for m in _PROGRESS_FIELD.finditer(text):
        val = m.group(1).replace('\\"', '"').strip()
        if val and val not in names:
            names.append(val)
    if names:
        return "正在撰写：" + "、".join(names[-6:])
    n = len(text)
    if n == 0:
        return "思考中…"
    return f"正在生成…（{n} 字符）"


async def stream_chat(messages, tools=None):
    """异步生成器。"""
    cfg = get_config()
    _require_key(cfg)

    payload = {
        "model": cfg.get("model", "gpt-4o-mini"),
        "messages": messages,
        "stream": True,
        "temperature": cfg_float(cfg, "temperature", 0.8),
        "max_tokens": cfg_int(cfg, "max_tokens", 4096),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    timeout = httpx.Timeout(connect=15, read=600, write=60, pool=60)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", _endpoint(cfg), json=payload, headers=_auth_headers(cfg)
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")[:500]
                    raise LLMError(f"API 返回 {resp.status_code}: {body}")
                tool_calls_acc: dict = {}
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning = (
                        delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or delta.get("thinking")
                    )
                    if reasoning:
                        yield {"type": "reasoning", "text": reasoning}
                    content = delta.get("content")
                    if content:
                        yield {"type": "text", "text": content}
                    for tc in delta.get("tool_calls") or []:
                        i = tc.get("index", 0)
                        slot = tool_calls_acc.setdefault(
                            i, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                        if fn.get("name") or fn.get("arguments"):
                            yield {
                                "type": "tool_call_delta",
                                "index": i,
                                "name": fn.get("name") or "",
                                "arguments": fn.get("arguments") or "",
                            }
    except httpx.HTTPError as e:
        raise LLMError(f"网络错误：{e}") from e

    if tool_calls_acc:
        calls = []
        for i in sorted(tool_calls_acc):
            slot = tool_calls_acc[i]
            args = {}
            try:
                args = json.loads(slot["arguments"] or "{}")
            except ValueError:
                args = {}
            calls.append({"id": slot["id"] or f"call_{i}", "name": slot["name"], "arguments": args})
        yield {"type": "tool_calls", "calls": calls}


async def _chat_blocking(messages) -> str:
    """非流式一次拿全量回复（访谈/JSON 任务更稳、更快结束）。"""
    cfg = get_config()
    _require_key(cfg)
    payload = {
        "model": cfg.get("model", "gpt-4o-mini"),
        "messages": messages,
        "stream": False,
        "temperature": cfg_float(cfg, "temperature", 0.8),
        "max_tokens": cfg_int(cfg, "max_tokens", 4096),
    }
    timeout = httpx.Timeout(connect=15, read=120, write=60, pool=60)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_endpoint(cfg), json=payload, headers=_auth_headers(cfg))
            if resp.status_code != 200:
                body = resp.text[:500]
                raise LLMError(f"API 返回 {resp.status_code}: {body}")
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise LLMError("API 未返回 choices")
            msg = choices[0].get("message") or {}
            return (msg.get("content") or "").strip()
    except httpx.HTTPError as e:
        raise LLMError(f"网络错误：{e}") from e


async def chat(messages, *, stream: bool = True) -> str:
    if not stream:
        return await _chat_blocking(messages)
    parts = []
    async for ev in stream_chat(messages, tools=None):
        if ev["type"] == "text":
            parts.append(ev["text"])
    return "".join(parts)
