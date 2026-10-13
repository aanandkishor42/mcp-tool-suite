"""Web research tool: search, fetch pages, and synthesize a cited summary."""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.registry import ToolCallable
from mcp_tool_suite.services.documents import load_text

_SYSTEM = (
    "You are a research assistant. Using ONLY the numbered sources provided, write a "
    "concise, factual synthesis of the query with inline citations like [1], [2]. "
    "Flag any disagreement between sources. If the sources do not answer the query, "
    "say so. Do not invent sources."
)

_MAX_SOURCE_CHARS = 4000


class WebResearchTool:
    name = "web_research"
    description = (
        "Search the web for a query, fetch the top pages, and return a synthesized, "
        "cited summary of what those pages say. Uses a pluggable search provider "
        "(DuckDuckGo by default, no API key needed)."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def web_research(query: str, max_sources: int = 5) -> dict:
            """Research a query across the web and return a cited summary."""
            results = await ctx.search.search(query, max_results=max_sources)
            if not results:
                return {
                    "query": query,
                    "sources": [],
                    "summary": "No search results were returned (the search provider may be "
                    "disabled or offline).",
                }

            fetched: list[dict[str, object]] = []
            blocks: list[str] = []
            for i, result in enumerate(results, start=1):
                try:
                    page_text = await load_text(result.url, timeout=ctx.settings.request_timeout)
                except Exception as exc:  # network / parse failures must not kill the tool
                    page_text = ""
                    fetched_note: str | None = f"fetch failed: {type(exc).__name__}"
                else:
                    fetched_note = None
                excerpt = (page_text or result.snippet)[:_MAX_SOURCE_CHARS]
                fetched.append(
                    {
                        "title": result.title,
                        "url": result.url,
                        "note": fetched_note,
                    }
                )
                blocks.append(f"[{i}] {result.title} ({result.url})\n{excerpt}")

            messages = [
                ChatMessage("system", _SYSTEM),
                ChatMessage("user", f"Query: {query}\n\nSources:\n\n" + "\n\n".join(blocks)),
            ]
            summary = await ctx.llm.complete(messages)
            return {"query": query, "sources": fetched, "summary": summary}

        return web_research
