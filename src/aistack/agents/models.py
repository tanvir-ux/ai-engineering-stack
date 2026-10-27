"""Model provider selection. One interface, three back ends: fake (default), OpenAI, Gemini.

    AISTACK_LLM_MODE=fake      deterministic test double, no key needed (default, used in CI)
    AISTACK_LLM_MODE=openai    needs OPENAI_API_KEY   (OPENAI_MODEL, default gpt-4o-mini)
    AISTACK_LLM_MODE=gemini    needs GEMINI_API_KEY   (GEMINI_MODEL, via Google's OpenAI-
                               compatible endpoint)

The real providers are wired but not exercised in CI because that needs paid or personal keys.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx2 as httpx
from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from aistack.agents.fake_llm import make_transport
from aistack.config import Settings

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass
class ModelBundle:
    model: OpenAIChatCompletionsModel
    mode: str
    name: str


def build_model(settings: Settings, *, fake_delay: float = 0.0) -> ModelBundle:
    # The Agents SDK uploads traces to OpenAI by default. Keep that off; observability goes
    # through OpenTelemetry / Langfuse instead (see aistack.observability).
    set_tracing_disabled(True)
    mode = settings.llm_mode
    if mode == "fake":
        client = AsyncOpenAI(
            api_key="fake-key",
            base_url="http://fake-llm.invalid/v1",
            http_client=httpx.AsyncClient(transport=make_transport(fake_delay)),
        )
        name = "fake-deterministic-1"
    elif mode == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("AISTACK_LLM_MODE=openai needs OPENAI_API_KEY")
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        name = settings.openai_model
    elif mode == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("AISTACK_LLM_MODE=gemini needs GEMINI_API_KEY")
        client = AsyncOpenAI(api_key=settings.gemini_api_key, base_url=GEMINI_BASE_URL)
        name = settings.gemini_model
    else:
        raise RuntimeError(f"unknown AISTACK_LLM_MODE {mode!r}")
    return ModelBundle(OpenAIChatCompletionsModel(model=name, openai_client=client), mode, name)
