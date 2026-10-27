"""FastAPI gateway: authentication, rate limiting, request tracing and streaming chat.

Endpoints
    GET  /health            liveness (no auth)
    GET  /ready             readiness: graph, checkpointer and signing keys are usable
    GET  /me                the verified identity, its classes and the tools it may use
    POST /chat              run the workflow, streamed as Server-Sent Events
    POST /approve           resume a run that is waiting for human approval, streamed as SSE
    GET  /threads/{id}      the state of one of the caller's own runs
    /idp/*                  the local mock identity provider (only when AISTACK_IDP_MODE=mock)
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from opentelemetry import trace
from opentelemetry.propagate import extract
from pydantic import BaseModel, Field

from aistack.agents.models import build_model
from aistack.agents.roles import Agents
from aistack.auth.idp import MockIdP, build_router
from aistack.auth.policy import TOOL_PERMISSION, Principal, can_use_tool
from aistack.auth.verifier import AuthError, JWTVerifier, bearer_token, http_jwks_source
from aistack.config import Settings, get_settings
from aistack.gateway.ratelimit import RateLimiter
from aistack.mcp_tools.service import KnowledgeService
from aistack.observability.tracing import langfuse_callbacks, setup_tracing, traced
from aistack.orchestration.graph import Credentials, Deps, build_graph
from aistack.orchestration.tools import LocalToolGateway, MCPToolGateway, ToolGateway

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ApproveRequest(BaseModel):
    thread_id: str = Field(min_length=8, max_length=64)
    approved: bool


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


class Runtime:
    """Everything the endpoints share. Built once at start-up."""

    def __init__(
        self,
        settings: Settings,
        tools: ToolGateway,
        agents: Agents,
        verifier: JWTVerifier,
        idp: MockIdP | None,
    ) -> None:
        self.settings, self.tools, self.agents = settings, tools, agents
        self.verifier, self.idp = verifier, idp
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self.graph: Any = None


def principal_dep(request: Request) -> Principal:
    rt: Runtime = request.app.state.runtime
    try:
        token = bearer_token(request.headers.get("authorization"))
        principal = rt.verifier.verify(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    wait = rt.limiter.check(principal.sub)
    if wait:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    request.state.token = token
    return principal


Authed = Annotated[Principal, Depends(principal_dep)]


def create_app(
    settings: Settings | None = None,
    *,
    tools: ToolGateway | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> FastAPI:
    """Build the app. Tests inject `tools` and `checkpointer`; production uses the defaults."""
    settings = settings or get_settings()
    setup_tracing()
    idp = (
        MockIdP(
            settings.oidc_issuer,
            settings.oidc_audience,
            settings.oidc_client_id,
            settings.oidc_redirect_prefixes,
            key_file=settings.idp_key_file or None,
        )
        if settings.idp_mode == "mock"
        else None
    )
    source = idp.jwks if idp else http_jwks_source(settings.jwks_url)
    verifier = JWTVerifier(settings.oidc_issuer, settings.oidc_audience, source)
    if tools is None:
        tools = (
            LocalToolGateway(
                KnowledgeService.from_paths(settings.gold_chunks_path, settings.tickets_path)
            )
            if settings.tool_transport == "local"
            else MCPToolGateway(settings.mcp_url)
        )
    rt = Runtime(settings, tools, Agents(build_model(settings)), verifier, idp)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        deps = Deps(rt.agents, rt.tools)
        if checkpointer is not None:
            rt.graph = build_graph(deps, checkpointer)
            yield
            return
        Path(settings.checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as saver:
            rt.graph = build_graph(deps, saver)
            yield

    app = FastAPI(title="Meridian knowledge copilot API", version="1.0.0", lifespan=lifespan)
    app.state.runtime = rt
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "traceparent"],
        expose_headers=["X-Request-ID", "X-Trace-Id", "Retry-After"],
    )

    @app.middleware("http")
    async def tracing_middleware(request: Request, call_next: Any) -> Any:
        rid = request.headers.get("x-request-id", "")
        rid = rid if _REQUEST_ID.match(rid) else uuid.uuid4().hex
        request.state.request_id = rid
        parent = extract(dict(request.headers))
        tracer = trace.get_tracer("aistack.http")
        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}", context=parent
        ) as span:
            span.set_attribute("http.request_id", rid)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            ctx = span.get_span_context()
            response.headers["X-Request-ID"] = rid
            if ctx.is_valid:
                response.headers["X-Trace-Id"] = format(ctx.trace_id, "032x")
            return response

    if idp is not None:
        app.include_router(build_router(idp), prefix="/idp")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        checks = {"graph": rt.graph is not None}
        try:
            rt.verifier._refresh()
            checks["signing_keys"] = bool(rt.verifier._keys)
        except AuthError:
            checks["signing_keys"] = False
        ok = all(checks.values())
        return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)

    @app.get("/me")
    async def me(principal: Authed) -> dict[str, Any]:
        return {
            "sub": principal.sub,
            "email": principal.email,
            "name": principal.name,
            "roles": list(principal.roles),
            "document_classes": sorted(principal.classes),
            "tools": sorted(t for t in TOOL_PERMISSION if can_use_tool(principal, t)),
        }

    def run_config(principal: Principal, token: str, thread_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": thread_id, "auth": Credentials(principal, token)},
            "callbacks": langfuse_callbacks(),
        }

    async def stream_run(
        graph_input: Any, config: dict[str, Any], thread_id: str
    ) -> AsyncIterator[str]:
        yield _sse({"type": "start", "thread_id": thread_id})
        interrupted = False
        try:
            with traced("graph.run", thread=thread_id):
                async for mode, chunk in rt.graph.astream(
                    graph_input, config, stream_mode=["custom", "updates"]
                ):
                    if mode == "custom":
                        yield _sse(chunk)
                    elif "__interrupt__" in chunk:
                        interrupted = True
                        yield _sse(chunk["__interrupt__"][0].value)
        except Exception as exc:  # surface a clean error to the client, keep details in logs
            yield _sse({"type": "error", "message": type(exc).__name__})
            return
        yield _sse({"type": "done", "status": "awaiting_approval" if interrupted else "completed"})

    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}

    @app.post("/chat")
    async def chat(body: ChatRequest, request: Request, principal: Authed) -> StreamingResponse:
        thread_id = uuid.uuid4().hex
        config = run_config(principal, request.state.token, thread_id)
        state = {"question": body.message.strip(), "user_sub": principal.sub}
        return StreamingResponse(
            stream_run(state, config, thread_id), media_type="text/event-stream", headers=headers
        )

    async def owned_thread(thread_id: str, principal: Principal) -> Any:
        snap = await rt.graph.aget_state({"configurable": {"thread_id": thread_id}})
        if not snap.values or snap.values.get("user_sub") != principal.sub:
            raise HTTPException(status_code=404, detail="thread not found")  # hides existence
        return snap

    @app.post("/approve")
    async def approve(
        body: ApproveRequest, request: Request, principal: Authed
    ) -> StreamingResponse:
        snap = await owned_thread(body.thread_id, principal)
        if snap.next != ("approval",):
            raise HTTPException(status_code=409, detail="thread is not waiting for approval")
        config = run_config(principal, request.state.token, body.thread_id)
        return StreamingResponse(
            stream_run(Command(resume={"approved": body.approved}), config, body.thread_id),
            media_type="text/event-stream",
            headers=headers,
        )

    @app.get("/threads/{thread_id}")
    async def thread(thread_id: str, principal: Authed) -> Any:
        snap = await owned_thread(thread_id, principal)
        v = snap.values
        return {
            "thread_id": thread_id,
            "waiting_for_approval": snap.next == ("approval",),
            "question": v.get("question"),
            "answer": v.get("answer"),
            "citations": v.get("citations", []),
            "tool": v.get("tool"),
        }

    return app
