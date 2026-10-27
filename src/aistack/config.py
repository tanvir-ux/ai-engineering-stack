"""Central configuration. Everything is read from environment variables (see `.env.example`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AISTACK_", env_file=".env", extra="ignore")

    # Model layer
    llm_mode: str = "fake"  # fake | openai | gemini
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")

    # Data / retrieval
    gold_chunks_path: Path = REPO_ROOT / "artifacts" / "gold" / "chunks.parquet"
    tickets_path: Path = REPO_ROOT / "artifacts" / "gold" / "tickets.parquet"
    vector_store: str = "local"  # local | pinecone
    pinecone_api_key: str = Field(default="", validation_alias="PINECONE_API_KEY")
    pinecone_index: str = Field(default="aistack-chunks", validation_alias="PINECONE_INDEX")

    # Auth
    idp_mode: str = "mock"  # mock | external
    oidc_issuer: str = "http://localhost:8000/idp"
    oidc_audience: str = "aistack-api"
    oidc_client_id: str = "aistack-web"
    oidc_redirect_prefixes: list[str] = ["http://localhost", "http://127.0.0.1"]
    idp_key_file: str = ""  # mock IdP only: persist the dev signing key here (mode 0600)
    oidc_jwks_url: str = ""  # defaults to <issuer>/jwks.json

    # Services
    tool_transport: str = "mcp"  # mcp (separate FastMCP server) | local (in-process, for tests)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    mcp_url: str = "http://127.0.0.1:8001/mcp/"
    mcp_internal_secret: str = ""  # optional shared secret between API and MCP (defence in depth)
    checkpoint_db: str = str(REPO_ROOT / ".checkpoints" / "graph.sqlite")
    rate_limit_per_minute: int = 30

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer.rstrip('/')}/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
