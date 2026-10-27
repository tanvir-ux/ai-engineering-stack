from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aistack.observability import tracing


def test_traced_records_attributes() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing._tracer = provider.get_tracer("test")
    with tracing.traced("node.answer", user="u1", model="m"):
        pass
    span = exporter.get_finished_spans()[0]
    assert span.name == "node.answer"
    assert span.attributes["aistack.user"] == "u1"  # type: ignore[index]
    tracing._tracer = trace.get_tracer("aistack")


def test_langfuse_is_off_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert tracing.langfuse_callbacks() == []


def test_langfuse_import_failure_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    import builtins

    real = builtins.__import__

    def fake(name: str, *a: object, **k: object) -> object:
        if name.startswith("langfuse"):
            raise ImportError(name)
        return real(name, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake)
    assert tracing.langfuse_callbacks() == []
