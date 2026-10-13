"""Build the configured LLM and embedding providers from settings."""

from __future__ import annotations

from mcp_tool_suite.config import Settings
from mcp_tool_suite.providers.anthropic import AnthropicProvider
from mcp_tool_suite.providers.base import EmbeddingProvider, LLMProvider
from mcp_tool_suite.providers.fake import FakeLLMProvider
from mcp_tool_suite.providers.hashing import HashingEmbeddings
from mcp_tool_suite.providers.openai_compatible import (
    OpenAICompatibleEmbeddings,
    OpenAICompatibleProvider,
)

# Reasonable embedding dimensions per backend when talking to OpenAI-compatible APIs.
_OPENAI_EMBED_DIM = 1536


def build_llm_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    model = settings.resolved_llm_model()
    timeout = settings.request_timeout

    if provider == "fake":
        return FakeLLMProvider(default_model=model)
    if provider == "groq":
        return OpenAICompatibleProvider(
            name="groq",
            base_url=settings.groq_base_url,
            default_model=model,
            api_key=settings.groq_api_key,
            timeout=timeout,
        )
    if provider == "openai":
        return OpenAICompatibleProvider(
            name="openai",
            base_url=settings.openai_base_url,
            default_model=model,
            api_key=settings.openai_api_key,
            timeout=timeout,
        )
    if provider == "ollama":
        return OpenAICompatibleProvider(
            name="ollama",
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            default_model=model,
            api_key="ollama",  # Ollama ignores the key but the client sends one
            timeout=timeout,
        )
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            default_model=model,
            base_url=settings.anthropic_base_url,
            timeout=timeout,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embed_provider
    model = settings.resolved_embed_model()
    timeout = settings.request_timeout

    if provider == "hashing":
        return HashingEmbeddings()
    if provider == "openai":
        return OpenAICompatibleEmbeddings(
            name="openai",
            base_url=settings.openai_base_url,
            default_model=model,
            dimension=_OPENAI_EMBED_DIM,
            api_key=settings.openai_api_key,
            timeout=timeout,
        )
    if provider == "ollama":
        return OpenAICompatibleEmbeddings(
            name="ollama",
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            default_model=model,
            dimension=768,  # nomic-embed-text
            api_key="ollama",
            timeout=timeout,
        )
    raise ValueError(f"Unknown embedding provider: {provider}")
