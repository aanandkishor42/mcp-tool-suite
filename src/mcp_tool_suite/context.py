"""Shared application context: settings plus wired-up services (dependency injection)."""

from __future__ import annotations

from dataclasses import dataclass

from mcp_tool_suite.config import Settings, get_settings
from mcp_tool_suite.providers.base import EmbeddingProvider, LLMProvider
from mcp_tool_suite.providers.router import build_embedding_provider, build_llm_provider
from mcp_tool_suite.services.rag import RagService
from mcp_tool_suite.services.usage import TrackedLLMProvider, UsageTracker
from mcp_tool_suite.services.vectorstore import InMemoryVectorStore, VectorStore
from mcp_tool_suite.services.web import DuckDuckGoSearch, NullSearch, SearchProvider


@dataclass(slots=True)
class AppContext:
    settings: Settings
    llm: LLMProvider
    embedder: EmbeddingProvider
    store: VectorStore
    rag: RagService
    search: SearchProvider
    usage: UsageTracker


def build_search_provider(settings: Settings) -> SearchProvider:
    if settings.web_search_provider == "none":
        return NullSearch()
    return DuckDuckGoSearch(timeout=settings.request_timeout)


def build_vector_store(settings: Settings, embedder: EmbeddingProvider) -> VectorStore:
    if settings.vector_store == "pgvector":
        if not settings.pgvector_dsn:
            raise ValueError("VECTOR_STORE=pgvector requires PGVECTOR_DSN to be set")
        try:
            from mcp_tool_suite.services.pgvector_store import PgVectorStore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "VECTOR_STORE=pgvector requires the 'pgvector' extra: "
                'pip install "mcp-tool-suite[pgvector]"'
            ) from exc
        return PgVectorStore(
            settings.pgvector_dsn,
            dimension=embedder.dimension,
            table=settings.pgvector_table,
        )
    return InMemoryVectorStore(persist_dir=settings.data_dir)


def build_context(settings: Settings | None = None) -> AppContext:
    settings = settings or get_settings()
    usage = UsageTracker()
    if settings.llm_input_price_per_1k is not None or settings.llm_output_price_per_1k is not None:
        default_input, default_output = usage.price_for(settings.llm_provider)
        usage.set_prices(
            settings.llm_provider,
            settings.llm_input_price_per_1k
            if settings.llm_input_price_per_1k is not None
            else default_input,
            settings.llm_output_price_per_1k
            if settings.llm_output_price_per_1k is not None
            else default_output,
        )
    llm = TrackedLLMProvider(build_llm_provider(settings), usage)
    embedder = build_embedding_provider(settings)
    store = build_vector_store(settings, embedder)
    rag = RagService(settings, llm, embedder, store)
    search = build_search_provider(settings)
    return AppContext(
        settings=settings,
        llm=llm,
        embedder=embedder,
        store=store,
        rag=rag,
        search=search,
        usage=usage,
    )
