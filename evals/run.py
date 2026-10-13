"""Per-tool evaluation harness (like RAG-eval) for the MCP Tool Suite.

Run the harness against the built-in tool suite to measure basic quality
signals (keyword coverage, answered rate, citation count) for offline-safe
configurations.

Usage (from mcp-tool-suite dir):

  $env:LLM_PROVIDER="fake"; $env:EMBED_PROVIDER="hashing"
  python -m evals.run --samples evals/data/sample.json --output evals/results/sample.json

Or programmatically via evals.runner.PerToolEvaluator.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from mcp_tool_suite.context import build_context

from evals.runner import PerToolEvaluator
from evals.testset import load_eval_samples, save_eval_results


async def main() -> None:
  parser = argparse.ArgumentParser(description="Per-tool eval harness")
  parser.add_argument("--samples", type=Path, default=Path("evals/data/sample.json"), help="Path to JSON samples")
  parser.add_argument("--output", type=Path, default=Path("evals/results/sample.json"), help="Path to write results JSON")
  args = parser.parse_args()

  samples = load_eval_samples(args.samples)
  evaluator = PerToolEvaluator(build_context())
  start = time.perf_counter()
  results = await evaluator.run(samples)
  elapsed = time.perf_counter() - start
  results["meta"] = {
      "samples_loaded": len(samples),
      "elapsed_seconds": round(elapsed, 3),
  }
  save_eval_results(args.output, results)


if __name__ == "__main__":
  asyncio.run(main())
