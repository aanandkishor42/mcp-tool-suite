"""Per-tool evaluation harness (like RAG-eval) for the MCP Tool Suite.

Runs every sample through its target tool and aggregates offline quality signals
(keyword coverage, answered rate, static-analysis/table checks, ...). Fully
offline with the ``fake`` LLM, ``hashing`` embeddings and ``none`` search.

Programmatic use:

    from mcp_tool_suite.context import build_context
    from evals.runner import PerToolEvaluator
    from evals.testset import load_eval_samples

    evaluator = PerToolEvaluator(build_context())
    results = await evaluator.run(load_eval_samples(Path("evals/data/sample.json")))
"""

from __future__ import annotations

from typing import Any

from mcp_tool_suite.context import AppContext

from evals.evaluators import OfflineMetrics, evaluate_sample
from evals.testset import EvalSample

__all__ = ["PerToolEvaluator", "OfflineMetrics"]


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise per-sample results, overall and grouped by tool."""
    ok = [r for r in results if not r.get("error")]
    coverage = [
        r["metrics"]["keyword_coverage"]
        for r in ok
        if isinstance(r.get("metrics", {}).get("keyword_coverage"), (int, float))
    ]
    qa = [r for r in ok if r["tool"] == "document_qa"]

    by_tool: dict[str, dict[str, Any]] = {}
    for result in ok:
        by_tool.setdefault(result["tool"], {"count": 0})
        by_tool[result["tool"]]["count"] += 1
    for tool, summary in by_tool.items():
        rows = [r for r in ok if r["tool"] == tool]
        numeric_keys = {
            key
            for r in rows
            for key, value in r["metrics"].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        for key in sorted(numeric_keys):
            values = [
                r["metrics"][key]
                for r in rows
                if isinstance(r["metrics"].get(key), (int, float))
                and not isinstance(r["metrics"].get(key), bool)
            ]
            if values:
                summary[f"mean_{key}"] = round(sum(values) / len(values), 4)

    return {
        "count": len(ok),
        "error_count": len(results) - len(ok),
        "mean_keyword_coverage": round(sum(coverage) / len(coverage), 4) if coverage else 0.0,
        "answered_rate": (
            round(sum(1 for r in qa if r["metrics"].get("has_answer")) / len(qa), 4)
            if qa
            else 0.0
        ),
        "by_tool": by_tool,
    }


class PerToolEvaluator:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings

    async def evaluate(self, sample: EvalSample) -> dict[str, Any]:
        return await evaluate_sample(self.ctx, sample)

    async def run(self, samples: list[EvalSample]) -> dict[str, Any]:
        results = [await self.evaluate(sample) for sample in samples]
        return {"samples": results, "aggregate": aggregate(results)}
