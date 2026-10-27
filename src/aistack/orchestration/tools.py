"""Tool gateways: how the orchestration layer reaches the data layer.

`MCPToolGateway` calls the FastMCP server over streamable HTTP and forwards the caller's own
bearer token, so the MCP server authorises the *user*, not a shared service account.
`LocalToolGateway` calls the same `KnowledgeService` in-process; it is used by unit tests and by
the offline evaluation so they need no network.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastmcp import Client
from fastmcp.exceptions import ToolError

from aistack.auth.policy import Principal
from aistack.mcp_tools.service import KnowledgeService, NotFound, PermissionDenied


class ToolError_(Exception):
    """A tool call failed in a way the user should be told about."""


class ToolGateway(Protocol):
    async def call(
        self, principal: Principal, token: str, tool: str, args: dict[str, Any]
    ) -> Any: ...


class MCPToolGateway:
    def __init__(self, url: str) -> None:
        self.url = url

    async def call(self, principal: Principal, token: str, tool: str, args: dict[str, Any]) -> Any:
        try:
            async with Client(self.url, auth=token) as client:
                result = await client.call_tool(tool, args)
        except ToolError as exc:
            raise ToolError_(str(exc)) from exc
        return result.data


class LocalToolGateway:
    def __init__(self, service: KnowledgeService) -> None:
        self.service = service

    async def call(self, principal: Principal, token: str, tool: str, args: dict[str, Any]) -> Any:
        fn = getattr(self.service, tool, None)
        if fn is None:
            raise ToolError_(f"unknown tool {tool}")
        try:
            return fn(principal, **args)
        except (PermissionDenied, NotFound, ValueError) as exc:
            raise ToolError_(str(exc)) from exc
