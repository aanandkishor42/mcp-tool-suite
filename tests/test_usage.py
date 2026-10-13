from __future__ import annotations

import asyncio

from mcp_tool_suite.context import build_context
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.server import build_http_app, build_mcp_server
from mcp_tool_suite.services.usage import (
    DEFAULT_PRICES,
    TrackedLLMProvider,
    UsageTracker,
    estimate_tokens,
)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_tracker_records_tool_calls():
    tracker = UsageTracker()
    tracker.record_tool("semantic_search", duration_ms=10.0)
    tracker.record_tool("semantic_search", duration_ms=20.0)
    tracker.record_tool("document_qa", duration_ms=5.0, ok=False)

    summary = tracker.summary()
    assert summary["totals"]["tool_calls"] == 3
    assert summary["totals"]["tool_errors"] == 1
    assert summary["tools"]["semantic_search"]["count"] == 2
    assert summary["tools"]["semantic_search"]["avg_ms"] == 15.0
    assert summary["tools"]["document_qa"]["errors"] == 1


def test_tracker_estimates_cost():
    tracker = UsageTracker()
    tracker.set_prices("openai", 0.001, 0.002)
    tracker.record_llm(
        "openai", "gpt-4o-mini", input_tokens=1000, output_tokens=500, duration_ms=12.0
    )
    summary = tracker.summary()
    entry = summary["llms"]["openai:gpt-4o-mini"]
    assert entry["calls"] == 1
    # 1000/1000*0.001 + 500/1000*0.002 = 0.002
    assert entry["estimated_cost_usd"] == 0.002
    assert summary["totals"]["estimated_cost_usd"] == 0.002


def test_free_providers_cost_nothing():
    tracker = UsageTracker()
    tracker.record_llm("fake", "fake", input_tokens=1000, output_tokens=1000, duration_ms=1.0)
    assert tracker.summary()["totals"]["estimated_cost_usd"] == 0.0
    assert DEFAULT_PRICES["fake"] == (0.0, 0.0)


def test_tracked_llm_provider_records_usage():
    tracker = UsageTracker()

    class StubLLM:
        name = "openai"
        default_model = "gpt-4o-mini"

        async def complete(self, messages, *, model=None, temperature=0.2, max_tokens=None):
            return "answer" * 20

    provider = TrackedLLMProvider(StubLLM(), tracker)
    result = asyncio.run(provider.complete([ChatMessage("user", "hello world")]))
    assert result == "answer" * 20
    entry = tracker.summary()["llms"]["openai:gpt-4o-mini"]
    assert entry["calls"] == 1
    assert entry["input_tokens"] == estimate_tokens("hello world")
    assert entry["output_tokens"] == estimate_tokens("answer" * 20)


def test_build_context_wires_tracking(settings):
    ctx = build_context(settings)
    assert isinstance(ctx.usage, UsageTracker)
    assert isinstance(ctx.llm, TrackedLLMProvider)
    asyncio.run(ctx.llm.complete([ChatMessage("user", "hi there")]))
    summary = ctx.usage.summary()
    assert summary["totals"]["llm_calls"] == 1
    assert "fake:fake" in summary["llms"]


def test_context_price_override(settings):
    settings.llm_input_price_per_1k = 1.0
    settings.llm_output_price_per_1k = 2.0
    ctx = build_context(settings)
    assert ctx.usage.price_for("fake") == (1.0, 2.0)


def test_registry_tracking_preserves_tool_schema(settings):
    ctx = build_context(settings)
    server = build_mcp_server(ctx)
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert "document_qa" in by_name
    schema = by_name["document_qa"].input_schema
    assert "question" in schema.get("properties", {})

    # Calling through the server records usage via the wrapped callable.
    asyncio.run(ctx.rag.index("docs", "Paris is the capital of France."))
    asyncio.run(server.call_tool("semantic_search", {"query": "capital", "collection": "docs"}))
    assert ctx.usage.summary()["tools"]["semantic_search"]["count"] == 1


def test_stats_endpoint(tmp_path):
    from starlette.testclient import TestClient

    from mcp_tool_suite.config import Settings

    settings = Settings(
        llm_provider="fake",
        embed_provider="hashing",
        web_search_provider="none",
        data_dir=str(tmp_path / "index"),
        stateless_http=True,
    )
    app = build_http_app(settings)
    with TestClient(app) as client:
        response = client.get("/stats")
    assert response.status_code == 200
    body = response.json()
    assert "totals" in body
    assert body["totals"]["tool_calls"] == 0
