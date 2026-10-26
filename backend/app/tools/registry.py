"""官方MCP SDK客户端与受控注册表；只加载本机配置中的工具，不接受模型注册服务。"""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from langchain_core.tools import StructuredTool, ToolException
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from backend.app.core.config import ROOT_DIR

CONFIG = Path(os.getenv("MCP_SERVERS_FILE", "data/mcp/servers.json"))
if not CONFIG.is_absolute():
    CONFIG = ROOT_DIR / CONFIG


def read_config():
    if CONFIG.exists():
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        # 兼容已有本机配置，保留管理员的启停与白名单选择。
        for spec in config.get("servers", {}).values():
            if spec.get("args") == ["-m", "backend.app.integrations.mcp_server"]:
                spec["args"] = ["-m", "backend.app.tools.server"]
        return config
    return {
        "servers": {
            "web": {
                "enabled": True,
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "backend.app.tools.server"],
                "allow_tools": [
                    "web_search",
                    "fetch_product_page",
                    "current_time",
                    "calculate_purchase_cost",
                    "compare_products",
                    "calculate_service_window",
                ],
                "retry_tools": [
                    "web_search",
                    "fetch_product_page",
                    "current_time",
                    "calculate_purchase_cost",
                    "compare_products",
                    "calculate_service_window",
                ],
            }
        }
    }


@asynccontextmanager
async def session(spec):
    if spec.get("transport") == "stdio":
        # subprocess只接收运维明确配置的环境；不把聊天身份、cookie或整个环境自动传过去。
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "HOME",
                "SSL_CERT_FILE",
            }
        }
        # 内置联网服务接收明确的检索配置，其他第三方进程仍使用最小环境。
        if spec.get("args") == ["-m", "backend.app.tools.server"]:
            env.update(
                {
                    k: v
                    for k, v in os.environ.items()
                    if k.startswith("WEB_") or k == "TAVILY_API_KEY"
                }
            )
        env.update(spec.get("env", {}))
        params = StdioServerParameters(
            command=spec["command"], args=spec.get("args", []), cwd=str(ROOT_DIR), env=env
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as active:
                await active.initialize()
                yield active
    elif spec.get("transport") in {"http", "streamable_http"}:
        # 地址、凭证由本机配置控制，API只能启用/停用已有配置。
        async with httpx.AsyncClient(
            headers=spec.get("headers", {}), timeout=30, follow_redirects=False
        ) as http:
            async with streamable_http_client(spec["url"], http_client=http) as (read, write, _):
                async with ClientSession(read, write) as active:
                    await active.initialize()
                    yield active
    else:
        raise ValueError("只支持 stdio 和 Streamable HTTP")


class MCPRegistry:
    def __init__(self):
        self.tools = []
        self.status = []
        self._lock = asyncio.Lock()

    async def reload(self):
        async with self._lock:
            tools = []
            statuses = []
            for name, spec in read_config().get("servers", {}).items():
                row = {
                    "name": name,
                    "enabled": bool(spec.get("enabled", True)),
                    "transport": spec.get("transport"),
                    "tools": [],
                    "status": "disabled",
                }
                if row["enabled"]:
                    try:
                        async with asyncio.timeout(25):
                            async with session(spec) as active:
                                listed = await active.list_tools()
                        for item in listed.tools:
                            if (
                                item.name not in spec.get("allow_tools", [])
                                or not item.annotations
                                or item.annotations.readOnlyHint is not True
                            ):
                                continue
                            if item.name in {
                                "lookup_order",
                                "search_products",
                                "search_faq",
                                "recall_preferences",
                                "request_human_service",
                                "export_consultation_pdf",
                                "list_saved_documents",
                            }:
                                raise ValueError("MCP服务不能覆盖原生业务工具")
                            if any(t.name == item.name for t in tools):
                                raise ValueError("MCP工具名冲突")

                            tool = StructuredTool(
                                name=item.name,
                                description=item.description or item.name,
                                args_schema=item.inputSchema,
                                coroutine=tool_caller(spec, item.name),
                                metadata={
                                    "mcp_server": name,
                                    "read_only": True,
                                    "retryable": item.name in spec.get("retry_tools", [])
                                    and item.annotations.idempotentHint is True,
                                },
                            )
                            tools.append(tool)
                            row["tools"].append(item.name)
                        row["status"] = "online"
                    except Exception:
                        row["status"] = "unavailable"
                statuses.append(row)
            self.tools = tools
            self.status = statuses
            return statuses

    async def invoke(self, name, args):
        tool = next((t for t in self.tools if t.name == name), None)
        if not tool:
            raise RuntimeError("该MCP工具未启用")
        value = await tool.ainvoke(args)
        return json.loads(value) if isinstance(value, str) else value


registry = MCPRegistry()


def tool_caller(spec, name):
    # 用闭包绑定服务身份，不能通过工具参数 _spec/_name 改写目的服务。
    async def call(**kwargs):
        async with asyncio.timeout(40):
            async with session(spec) as active:
                result = await active.call_tool(name, kwargs)
        if result.isError:
            raise ToolException("MCP工具未能完成读取")
        value = result.structuredContent
        if value is None:
            value = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass
        if isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
        return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value

    return call
