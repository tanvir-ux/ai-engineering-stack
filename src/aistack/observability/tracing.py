"""Observability: OpenTelemetry spans, with optional Langfuse and LangSmith hooks.

* OpenTelemetry is always on as an API. With `OTEL_EXPORTER_OTLP_ENDPOINT` set, spans are
  exported over OTLP/HTTP to any collector (Jaeger, Tempo, Grafana, Datadog, Honeycomb).
  Without it, spans stay in-process and cost almost nothing.
* Langfuse: set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (and optionally `LANGFUSE_HOST`)
  and the LangGraph run gets a Langfuse callback handler. Not exercised in CI.
* LangSmith: set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`; LangGraph picks these up by
  itself, so no code is needed here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

_tracer = trace.get_tracer("aistack")
_configured = False


def setup_tracing(exporter: SpanExporter | None = None, service_name: str = "aistack-api") -> bool:
    """Install a tracer provider once. Returns True if spans will be exported somewhere."""
    global _configured, _tracer
    if _configured:
        return exporter is not None
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    exported = False
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        exported = True
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        exported = True
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("aistack")
    _configured = True
    return exported


@contextmanager
def traced(name: str, **attrs: Any) -> Iterator[trace.Span]:
    with _tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            span.set_attribute(f"aistack.{k}", str(v))
        yield span


def langfuse_callbacks() -> list[Any]:
    """Return a Langfuse LangChain/LangGraph callback handler if keys are configured."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        return []
    return [CallbackHandler()]
