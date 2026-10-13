from __future__ import annotations

import asyncio

from mcp_tool_suite.context import build_context
from mcp_tool_suite.services.documents import html_to_text
from mcp_tool_suite.tools import default_plugins

_CODE = """\
def compute(a, b=[]):
    try:
        return eval(a)
    except:
        return b
"""

_CSV = "name,age,city\nAlice,30,NY\nBob,25,LA\nCara,,NY\n"


def _plugin(name):
    return next(p for p in default_plugins() if p.name == name)


def test_review_code_offline(settings):
    ctx = build_context(settings)
    out = asyncio.run(_plugin("review_code").create(ctx)(_CODE, "auto"))
    assert out["language"] == "python"
    assert out["static_analysis"]["syntax_ok"] is True
    assert any(f["severity"] == "high" for f in out["static_analysis"]["findings"])
    assert out["review"]


def test_analyze_data_offline(settings):
    ctx = build_context(settings)
    out = asyncio.run(_plugin("analyze_data").create(ctx)(_CSV))
    assert out["rows"] == 3
    assert "age" in out["profiles"]
    assert out["insights"]


def test_generate_report_grounded_and_empty(settings):
    ctx = build_context(settings)
    asyncio.run(ctx.rag.index("docs", "Widgets are small mechanical parts used in machines."))
    fn = _plugin("generate_report").create(ctx)

    grounded = asyncio.run(fn("Widgets", "docs"))
    assert grounded["sources_used"] >= 1
    assert grounded["report"]

    empty = asyncio.run(fn("Nothing", "empty-collection"))
    assert "No context" in empty["report"]


def test_web_research_handles_no_results(settings):
    ctx = build_context(settings)
    out = asyncio.run(_plugin("web_research").create(ctx)("anything at all"))
    assert out["sources"] == []
    assert "No search results" in out["summary"]


def test_html_to_text_strips_markup():
    markup = "<html><head><style>x{}</style></head><body><h1>Hi</h1><p>A &amp; B</p></body></html>"
    text = html_to_text(markup)
    assert "Hi" in text
    assert "A & B" in text
    assert "x{}" not in text
