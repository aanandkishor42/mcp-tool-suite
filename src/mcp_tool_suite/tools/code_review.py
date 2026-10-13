"""Code reviewer tool: static analysis (Python) plus an LLM review."""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.registry import ToolCallable
from mcp_tool_suite.services.code_analysis import analyze_python, looks_like_python
from mcp_tool_suite.services.documents import load_text

_SYSTEM = (
    "You are a senior engineer performing a code review. Using the static-analysis "
    "report and the code, list concrete issues grouped by severity (High/Medium/Low), "
    "each with the line number and a specific fix. Then give a short overall verdict. "
    "Be precise and avoid generic advice."
)

_MAX_CHARS = 12000


class ReviewCodeTool:
    name = "review_code"
    description = (
        "Review source code for bugs, style and security issues. Python is parsed "
        "with static analysis (functions, classes, imports, risky patterns); other "
        "languages are reviewed directly. The source may be an http(s) URL, a local "
        "file path, or raw code text."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def review_code(source: str, language: str = "auto") -> dict:
            """Review a code snippet or file and return findings plus suggestions."""
            code = await load_text(source, timeout=ctx.settings.request_timeout)
            window = code[:_MAX_CHARS]

            report: dict | None = None
            resolved_language = language
            if language in ("auto", "python") and looks_like_python(window):
                report = analyze_python(window).as_dict()
                resolved_language = "python"
            elif language == "auto":
                resolved_language = "unknown"

            static_block = ""
            if report is not None:
                findings = report["findings"]
                lines = "\n".join(
                    f"- [{f['severity']}] line {f['line']}: {f['message']}" for f in findings
                ) or "- (none)"
                static_block = (
                    f"\nStatic analysis found {len(findings)} issue(s):\n{lines}\n"
                )

            messages = [
                ChatMessage("system", _SYSTEM),
                ChatMessage(
                    "user",
                    f"Language: {resolved_language}{static_block}\n"
                    f"Code:\n```\n{window}\n```",
                ),
            ]
            review = await ctx.llm.complete(messages)
            return {
                "language": resolved_language,
                "static_analysis": report,
                "review": review,
                "truncated": len(code) > _MAX_CHARS,
            }

        return review_code
