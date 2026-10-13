from __future__ import annotations

import asyncio

from mcp_tool_suite.context import build_context
from mcp_tool_suite.registry import ToolRegistry
from mcp_tool_suite.tools import default_plugins


def test_default_plugins_have_names():
    names = ToolRegistry(default_plugins()).names()
    assert names == [
        "index_document",
        "semantic_search",
        "document_qa",
        "analyze_document",
        "review_code",
        "analyze_data",
        "web_research",
        "generate_report",
    ]


def test_index_then_answer_with_citations(settings):
    ctx = build_context(settings)
    info = asyncio.run(
        ctx.rag.index("docs", "The Eiffel Tower is located in Paris, the capital of France.")
    )
    assert info["chunks"] >= 1

    result = asyncio.run(ctx.rag.answer("docs", "Where is the Eiffel Tower?"))
    assert result["citations"]
    assert "Paris" in result["answer"]


def test_analyze_plugin_runs_offline(settings):
    ctx = build_context(settings)
    plugin = next(p for p in default_plugins() if p.name == "analyze_document")
    fn = plugin.create(ctx)
    out = asyncio.run(fn("A short raw document about widgets."))
    assert out["source"] == "A short raw document about widgets."
    assert out["characters"] > 0
