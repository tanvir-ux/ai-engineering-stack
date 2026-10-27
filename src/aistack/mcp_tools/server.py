"""FastMCP server exposing the data-layer tools over MCP (streamable HTTP or stdio).

Over HTTP every request must carry a valid bearer JWT (verified against the issuer's JWKS); the
caller's identity and roles then drive the same policy the API enforces. Over stdio there is no
HTTP, so a single development identity is taken from `AISTACK_STDIO_USER` (a persona id).

    python -m aistack.mcp_tools.server --transport http --port 8001
    python -m aistack.mcp_tools.server --transport stdio
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier as MCPJWTVerifier
from fastmcp.server.dependencies import get_access_token

from aistack.auth.idp import PERSONAS
from aistack.auth.policy import Principal
from aistack.config import get_settings
from aistack.mcp_tools.service import KnowledgeService, NotFound, PermissionDenied


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    roles = claims.get("roles", [])
    return Principal(
        sub=str(claims.get("sub", "")),
        email=str(claims.get("email", "")).lower(),
        name=str(claims.get("name", "")),
        roles=tuple(str(r) for r in roles) if isinstance(roles, list) else (),
    )


def build_server(
    service: KnowledgeService,
    *,
    auth: MCPJWTVerifier | None = None,
    stdio_persona: str | None = None,
) -> FastMCP:
    mcp: FastMCP = FastMCP("aistack-knowledge", auth=auth)

    def who() -> Principal:
        token = get_access_token()
        if token is not None:
            return principal_from_claims(dict(token.claims))
        if stdio_persona and stdio_persona in PERSONAS:
            p = PERSONAS[stdio_persona]
            return Principal(f"user:{stdio_persona}", p["email"], p["name"], tuple(p["roles"]))
        raise ToolError("unauthenticated")

    def guarded(fn: Any, *args: Any, **kw: Any) -> Any:
        try:
            return fn(who(), *args, **kw)
        except PermissionDenied as exc:
            raise ToolError(f"permission denied: {exc}") from exc
        except (NotFound, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    def search_documents(query: str, k: int = 4) -> list[dict[str, Any]]:
        """Search company documents the caller is allowed to read (hybrid BM25 + vector)."""
        return guarded(service.search_documents, query, k)  # type: ignore[no-any-return]

    @mcp.tool
    def get_document(doc_id: str) -> dict[str, Any]:
        """Fetch the full text of one document by id, if the caller may read it."""
        return guarded(service.get_document, doc_id)  # type: ignore[no-any-return]

    @mcp.tool
    def list_my_tickets(status: str | None = None) -> list[dict[str, Any]]:
        """List the caller's own IT tickets, optionally filtered by status."""
        return guarded(service.list_my_tickets, status)  # type: ignore[no-any-return]

    @mcp.tool
    def ticket_stats(category: str | None = None) -> dict[str, Any]:
        """Aggregate IT ticket statistics (volume, open count, resolution time)."""
        return guarded(service.ticket_stats, category)  # type: ignore[no-any-return]

    @mcp.tool
    def create_ticket(title: str, priority: str = "P3") -> dict[str, Any]:
        """Create an IT ticket for the caller. This changes state; clients should ask first."""
        return guarded(service.create_ticket, title, priority)  # type: ignore[no-any-return]

    return mcp


def auth_from_settings() -> MCPJWTVerifier:
    s = get_settings()
    return MCPJWTVerifier(jwks_uri=s.jwks_url, issuer=s.oidc_issuer, audience=s.oidc_audience)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["http", "stdio"], default="http")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    s = get_settings()
    service = KnowledgeService.from_paths(s.gold_chunks_path, s.tickets_path)
    if args.transport == "stdio":
        build_server(service, stdio_persona=os.environ.get("AISTACK_STDIO_USER", "alice")).run(
            transport="stdio"
        )
    else:
        build_server(service, auth=auth_from_settings()).run(
            transport="http", host=args.host, port=args.port
        )


if __name__ == "__main__":
    main()
