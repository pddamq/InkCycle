"""极简 MCP (Model Context Protocol) 客户端。

支持两种传输：
- stdio: 子进程 stdin/stdout 按行交换 JSON-RPC 2.0 消息
- http:  Streamable HTTP（POST JSON-RPC，响应为 JSON 或 SSE）

只实现 Agent 需要的三个方法：initialize / tools/list / tools/call。
"""
import asyncio
import json
import shlex
import time

import httpx

PROTOCOL_VERSION = "2024-11-05"
REQUEST_TIMEOUT = 120.0
CLIENT_INFO = {"name": "NovelAgent", "version": "1.0.0"}


class MCPError(Exception):
    pass


def _next_id():
    MCPConnection._counter += 1
    return MCPConnection._counter


class MCPConnection:
    _counter = 0

    def __init__(self, server_row: dict):
        self.row = server_row
        self.server_id = server_row["id"]
        self.name = server_row["name"]
        self.transport = server_row.get("transport", "stdio")
        self.command = server_row.get("command", "")
        self.args = server_row.get("args") or []
        if isinstance(self.args, str):
            try:
                self.args = json.loads(self.args)
            except ValueError:
                self.args = shlex.split(self.args)
        self.url = server_row.get("url", "")
        self.session_id: "str | None" = None
        self.tools: list = []
        self.status = "disconnected"  # disconnected/connecting/connected/error
        self.error = ""
        self._proc = None
        self._reader_task = None
        self._pending: dict = {}
        self._http = None
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------- 连接

    async def connect(self) -> list:
        async with self._lock:
            if self.status == "connected":
                return self.tools
            self.status = "connecting"
            self.error = ""
            try:
                if self.transport == "stdio":
                    await self._connect_stdio()
                else:
                    await self._connect_http()
                await self._initialize()
                self.tools = await self._list_tools()
                self.status = "connected"
                return self.tools
            except Exception as e:
                self.status = "error"
                self.error = str(e)
                await self._cleanup()
                raise MCPError(f"MCP 服务器 [{self.name}] 连接失败：{e}") from e

    async def _connect_stdio(self):
        cmd = [self.command] + [str(a) for a in self.args]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, FileNotFoundError) as e:
            raise MCPError(f"无法启动命令 {self.command}: {e}") from e
        self._reader_task = asyncio.create_task(self._stdio_reader())

    async def _stdio_reader(self):
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                try:
                    self._route(json.loads(line))
                except ValueError:
                    continue
        except Exception:
            pass
        finally:
            self._fail_pending("MCP 进程已退出")

    def _route(self, msg: dict):
        mid = msg.get("id")
        if mid is not None and mid in self._pending:
            fut = self._pending.pop(mid)
            if not fut.done():
                if "error" in msg and msg["error"]:
                    fut.set_exception(MCPError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result"))
        # notifications（无 id）与 server→client 请求忽略

    def _fail_pending(self, reason: str):
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MCPError(reason))
        self._pending.clear()

    async def _connect_http(self):
        if not self.url:
            raise MCPError("HTTP 传输需要填写 URL")
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=REQUEST_TIMEOUT, write=60, pool=60))

    async def _send(self, method: str, params=None, notification=False):
        if self.transport == "stdio":
            return await self._send_stdio(method, params, notification)
        return await self._send_http(method, params, notification)

    async def _send_stdio(self, method, params, notification):
        if not self._proc or self._proc.returncode is not None:
            raise MCPError("MCP 进程未运行")
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notification:
            msg["id"] = _next_id()
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        if notification:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()
            return None
        fut = asyncio.get_event_loop().create_future()
        self._pending[msg["id"]] = fut
        try:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()
        except Exception as e:
            self._pending.pop(msg["id"], None)
            raise MCPError(f"写入 MCP 进程失败：{e}") from e
        return await asyncio.wait_for(fut, REQUEST_TIMEOUT)

    async def _send_http(self, method, params, notification):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if notification:
            try:
                await self._http.post(self.url, json=msg, headers=headers)
            except httpx.HTTPError:
                pass
            return None
        msg["id"] = _next_id()
        try:
            resp = await self._http.post(self.url, json=msg, headers=headers)
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP 请求失败：{e}") from e
        if resp.status_code >= 400:
            raise MCPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        ctype = resp.headers.get("content-type", "")
        body = resp.text
        if "text/event-stream" in ctype:
            body = self._parse_sse(resp.text)
        try:
            data = json.loads(body)
        except ValueError:
            raise MCPError(f"无法解析响应：{body[:300]}")
        if data.get("error"):
            raise MCPError(str(data["error"]))
        return data.get("result")

    @staticmethod
    def _parse_sse(text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    return payload
        return text

    async def _initialize(self):
        result = await self._send("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        if result is None:
            raise MCPError("initialize 无响应")
        await self._send("notifications/initialized", None, notification=True)

    async def _list_tools(self) -> list:
        result = await self._send("tools/list", {})
        tools = (result or {}).get("tools") or []
        out = []
        for t in tools:
            out.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
            })
        return out

    # ---------------------------------------------------------- 调用

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self.status != "connected":
            raise MCPError(f"服务器 [{self.name}] 未连接")
        result = await self._send("tools/call", {"name": name, "arguments": arguments or {}})
        return self._format_result(result)

    @staticmethod
    def _format_result(result) -> str:
        if result is None:
            return ""
        if result.get("isError"):
            raise MCPError(str(result.get("content") or "工具执行失败"))
        parts = []
        for c in result.get("content") or []:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "resource":
                parts.append(json.dumps(c.get("resource", {}), ensure_ascii=False))
            else:
                parts.append(json.dumps(c, ensure_ascii=False))
        text = "\n".join(parts)
        return text[:8000] if text else json.dumps(result, ensure_ascii=False)[:8000]

    # ---------------------------------------------------------- 关闭

    async def close(self):
        self.status = "disconnected"
        await self._cleanup()

    async def _cleanup(self):
        self._fail_pending("连接已关闭")
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        if self._http:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None

    def info(self) -> dict:
        return {
            "id": self.server_id,
            "name": self.name,
            "status": self.status,
            "error": self.error,
            "tools": [
                {"name": t["name"], "description": t["description"][:200],
                 "inputSchema": t["inputSchema"]}
                for t in self.tools
            ],
            "connected_at": getattr(self, "_connected_at", ""),
        }


class MCPManager:
    """全局连接管理器：持有运行中的连接，供 Agent 工具调用。"""

    def __init__(self):
        self.connections: "dict[int, MCPConnection]" = {}

    def get(self, server_id: int) -> "MCPConnection | None":
        return self.connections.get(server_id)

    def connected(self) -> list:
        return [c for c in self.connections.values() if c.status == "connected"]

    async def connect(self, server_row: dict) -> list:
        conn = self.connections.get(server_row["id"])
        if conn and conn.status == "connected":
            return conn.tools
        if conn:
            await conn.close()
        conn = MCPConnection(server_row)
        conn._connected_at = time.strftime("%Y-%m-%d %H:%M:%S")
        tools = await conn.connect()
        self.connections[server_row["id"]] = conn
        return tools

    async def disconnect(self, server_id: int) -> bool:
        conn = self.connections.pop(server_id, None)
        if conn:
            await conn.close()
            return True
        return False

    async def disconnect_all(self):
        for sid in list(self.connections.keys()):
            await self.disconnect(sid)

    def statuses(self) -> dict:
        return {sid: {"status": c.status, "tools": len(c.tools), "error": c.error,
                      "connected_at": getattr(c, "_connected_at", "")}
                for sid, c in self.connections.items()}


manager = MCPManager()
