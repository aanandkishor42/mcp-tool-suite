"""Data analyzer tool: profile a dataset and explain it, optionally answering a question."""

from __future__ import annotations

import json

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.registry import ToolCallable
from mcp_tool_suite.services.data_analysis import profile_csv
from mcp_tool_suite.services.documents import load_text

_SYSTEM = (
    "You are a data analyst. Given a dataset's column profile and a small sample, "
    "explain what the data appears to contain and surface notable patterns, outliers "
    "and data-quality issues (missing values, skew). If a specific question is asked, "
    "answer it directly from the profile. Be concise and concrete."
)


class AnalyzeDataTool:
    name = "analyze_data"
    description = (
        "Profile a tabular dataset (CSV/TSV) and return per-column statistics plus "
        "AI-generated insights. The source may be an http(s) URL, a local file path, "
        "or raw CSV text. Optionally pass a question to answer about the data."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def analyze_data(source: str, question: str = "", sample_rows: int = 5) -> dict:
            """Profile a CSV dataset and return statistics and insights."""
            text = await load_text(source, timeout=ctx.settings.request_timeout)
            profile = profile_csv(text, sample_rows=sample_rows)

            profile_json = json.dumps(
                {"rows": profile["rows"], "columns": profile["columns"], "profiles": profile["profiles"]},
                ensure_ascii=False,
            )
            prompt = (
                f"Dataset profile:\n{profile_json}\n\n"
                f"Sample rows:\n{json.dumps(profile['sample'], ensure_ascii=False)}"
            )
            if question.strip():
                prompt += f"\n\nQuestion: {question.strip()}"

            insights = await ctx.llm.complete(
                [ChatMessage("system", _SYSTEM), ChatMessage("user", prompt)]
            )
            return {
                "rows": profile["rows"],
                "columns": profile["columns"],
                "profiles": profile["profiles"],
                "sample": profile["sample"],
                "insights": insights,
            }

        return analyze_data
