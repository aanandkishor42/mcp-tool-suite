"""Application configuration, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["groq", "ollama", "openai", "anthropic", "fake"]
EmbedProviderName = Literal["ollama", "openai", "hashing"]

DEFAULT_MODELS: dict[str, str] = {
    "groq": "llama-3.1-8b-instant",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "ollama": "llama3.2:3b",
    "fake": "fake",
}

DEFAULT_EMBED_MODELS: dict[str, str] = {
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
    "hashing": "hashing-256",
}


class Settings(BaseSettings):
    """Runtime settings. Prefix-free so env vars read naturally."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Server identity
    server_name: str = "MCP Tool Suite"
    server_version: str = "0.1.0"

    # Transport
    transport: Literal["stdio", "streamable-http"] = "streamable-http"
    host: str = "127.0.0.1"
    port: int = 8000
    mcp_path: str = "/mcp"
    stateless_http: bool = True

    # Auth
    auth_mode: Literal["none", "bearer", "oauth2"] = "none"
    api_key: str | None = None

    # OAuth 2.1 (used when auth_mode="oauth2")
    public_base_url: str | None = None  # e.g. https://mcp.example.com; default derived from host/port
    oauth_token_ttl: int = 3600
    oauth_refresh_ttl: int = 2592000
    oauth_demo_user: str = "admin"
    oauth_demo_password: str = "admin"

    # Providers
    llm_provider: LLMProviderName = "groq"
    embed_provider: EmbedProviderName = "hashing"
    web_search_provider: Literal["duckduckgo", "none"] = "duckduckgo"
    llm_model: str | None = None
    embed_model: str | None = None

    groq_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    groq_base_url: str = "https://api.groq.com/openai/v1"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    ollama_base_url: str = "http://localhost:11434"

    # RAG
    data_dir: str = "data/index"
    chunk_size: int = 900
    chunk_overlap: int = 150
    default_top_k: int = 4
    request_timeout: float = 60.0

    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]

    def resolved_embed_model(self) -> str:
        return self.embed_model or DEFAULT_EMBED_MODELS[self.embed_provider]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
