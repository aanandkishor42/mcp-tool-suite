"""Report generator tool: assemble grounded context into a Markdown report.

A natural future candidate for MCP **Tasks** (long-running work) when report
synthesis becomes expensive.
"""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.registry import ToolCallable

_SYSTEM = (
    "You are a technical writer. Produce a well-structured Markdown report on the "
    "topic using ONLY the provided context. Use headings, short paragraphs and bullet "
    "points. Add a short 'Sources' section listing the sources you used. If context is "
    "thin, say what is missing rather than inventing facts."
)

_MAX_PROVIDED_CHARS = 6000
_MAX_CONTEXT_CHUNKS = 8


class GenerateReportTool:
    name = "generate_report"
    description = (
        "Generate a structured Markdown report on a topic, grounded in a previously "
        "indexed collection and/or sources you pass in. Returns the report as Markdown."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def generate_report(
            topic: str,
            collection: str = "default",
            sources: str = "",
            max_words: int = 600,
        ) -> dict:
            """Generate a Markdown report grounded in indexed docs and/or given sources."""
            blocks: list[str] = []

            if ctx.store.has_collection(collection):
                hits = await ctx.rag.search(collection, topic, top_k=_MAX_CONTEXT_CHUNKS)
                for i, hit in enumerate(hits, start=1):
                    source = hit.metadata.get("source", "unknown")
                    blocks.append(f"[{i}] {hit.text} (source: {source})")

            if sources.strip():
                blocks.append("[provided] " + sources[:_MAX_PROVIDED_CHARS])

            if not blocks:
                return {
                    "topic": topic,
                    "report": "No context available. Index a document or pass `sources` first.",
                    "sources_used": 0,
                }

            messages = [
                ChatMessage("system", _SYSTEM),
                ChatMessage(
                    "user",
                    f"Topic: {topic}\nTarget length: about {max_words} words.\n\n"
                    f"Context:\n\n" + "\n\n".join(blocks),
                ),
            ]
            report = await ctx.llm.complete(messages)
            return {"topic": topic, "report": report, "sources_used": len(blocks)}

        return generate_report
