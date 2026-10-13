"""Usage/cost dashboard tool: report accumulated tool and LLM usage.

Mirrors the ``/stats`` HTTP endpoint so clients that only speak MCP can still
read the in-process usage and estimated-cost totals.
"""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.registry import ToolCallable


def render_usage(summary: dict) -> str:
    """Render a usage summary as a small Markdown dashboard."""
    totals = summary["totals"]
    lines = [
        "## Usage",
        "",
        f"- Tool calls: {totals['tool_calls']} ({totals['tool_errors']} errors)",
        f"- LLM calls: {totals['llm_calls']}",
        f"- Tokens: {totals['input_tokens']} in / {totals['output_tokens']} out",
        f"- Estimated cost: ${totals['estimated_cost_usd']:.6f}",
    ]
    if summary["tools"]:
        lines += ["", "### Tools", "", "| Tool | Calls | Errors | Avg ms |", "| --- | --- | --- | --- |"]
        for name, entry in summary["tools"].items():
            lines.append(
                f"| {name} | {entry['count']} | {entry['errors']} | {entry['avg_ms']} |"
            )
    if summary["llms"]:
        lines += [
            "",
            "### Models",
            "",
            "| Model | Calls | In | Out | Cost (USD) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for entry in summary["llms"].values():
            lines.append(
                f"| {entry['provider']}:{entry['model']} | {entry['calls']} | "
                f"{entry['input_tokens']} | {entry['output_tokens']} | "
                f"{entry['estimated_cost_usd']:.6f} |"
            )
    return "\n".join(lines)


class UsageStatsTool:
    name = "usage_stats"
    description = (
        "Report tool-call and LLM-call usage for this server session, including call "
        "counts, latency and estimated USD cost. Returns structured totals plus a "
        "Markdown dashboard."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def usage_stats() -> dict:
            """Return accumulated tool and LLM usage with estimated cost."""
            summary = ctx.usage.summary()
            return {**summary, "dashboard": render_usage(summary)}

        return usage_stats
