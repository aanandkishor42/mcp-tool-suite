"""Document analyzer tool: summarize and extract structure from any document."""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.registry import ToolCallable
from mcp_tool_suite.services.documents import load_text

_SYSTEM = (
    "You are a document analyst. Given a document, produce: a 2-3 sentence summary, "
    "then a bullet list of the key points, then a list of the notable entities "
    "(people, organizations, dates, figures). Be concise and factual."
)

_MAX_CHARS = 12000


class AnalyzeDocumentTool:
    name = "analyze_document"
    description = (
        "Analyze a document and return a summary, key points and notable entities. "
        "The source may be an http(s) URL, a local file path (PDF or text), or raw text."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def analyze_document(source: str, max_points: int = 5) -> dict:
            """Summarize a document and extract key points and entities."""
            text = await load_text(source, timeout=ctx.settings.request_timeout)
            if not text.strip():
                return {"source": source, "characters": 0, "analysis": "Empty document."}
            window = text[:_MAX_CHARS]
            messages = [
                ChatMessage("system", _SYSTEM),
                ChatMessage(
                    "user",
                    f"Analyze this document (at most {max_points} key points):\n\n{window}",
                ),
            ]
            analysis = await ctx.llm.complete(messages)
            return {
                "source": source,
                "characters": len(text),
                "truncated": len(text) > _MAX_CHARS,
                "analysis": analysis,
            }

        return analyze_document
