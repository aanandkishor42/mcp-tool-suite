from __future__ import annotations

import asyncio
from pathlib import Path

from mcp_tool_suite.context import build_context

from evals.evaluators import (
    TOOL_EVALUATORS,
    OfflineMetrics,
    evaluate_sample,
)
from evals.runner import PerToolEvaluator, aggregate
from evals.testset import EvalSample, load_eval_samples

_SAMPLE_FILE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample.json"


def test_eval_sample_defaults_to_document_qa():
    sample = EvalSample.from_dict({"question": "Q?", "reference": "A."})
    assert sample.tool == "document_qa"
    assert sample.input == {}
    assert sample.collection == "evals"


def test_eval_sample_parses_tool_and_input():
    sample = EvalSample.from_dict(
        {
            "question": "Review this",
            "tool": "review_code",
            "input": {"source": "eval(x)", "language": "python"},
            "metadata": {"expected_language": "python"},
        }
    )
    assert sample.tool == "review_code"
    assert sample.input["source"] == "eval(x)"
    assert sample.metadata["expected_language"] == "python"


def test_keyword_coverage_and_ratio():
    assert OfflineMetrics.keyword_coverage("alpha beta gamma", "alpha and gamma") == 0.6667
    assert OfflineMetrics.keyword_coverage("", "text") == 0.0
    assert OfflineMetrics.ratio_matched("found dangerous-call here", ["dangerous-call", "todo"]) == 0.5
    assert OfflineMetrics.set_ratio(["a", "b"], {"a"}) == 0.5


def test_has_answer():
    assert OfflineMetrics.has_answer("Here is the answer.") is True
    assert OfflineMetrics.has_answer("I don't know.") is False
    assert OfflineMetrics.has_answer("No documents are indexed.") is False


def test_registry_covers_every_tool():
    assert set(TOOL_EVALUATORS) == {
        "document_qa",
        "semantic_search",
        "analyze_document",
        "review_code",
        "analyze_data",
        "web_research",
        "generate_report",
        "email_assistant",
        "usage_stats",
    }


def test_sample_file_parses_and_covers_every_tool():
    samples = load_eval_samples(_SAMPLE_FILE)
    assert samples
    tools = {sample.tool for sample in samples}
    assert tools == set(TOOL_EVALUATORS)


def test_aggregate_groups_by_tool_and_ignores_errors_and_bools():
    results = [
        {"tool": "document_qa", "error": None, "metrics": {"keyword_coverage": 0.5, "has_answer": True}},
        {"tool": "document_qa", "error": None, "metrics": {"keyword_coverage": 0.25, "has_answer": False}},
        {
            "tool": "review_code",
            "error": None,
            "metrics": {"keyword_coverage": 0.75, "findings_count": 3, "language_match": True},
        },
        {"tool": "analyze_data", "error": "RuntimeError: boom", "metrics": {}},
    ]
    agg = aggregate(results)

    assert agg["count"] == 3
    assert agg["error_count"] == 1
    assert agg["mean_keyword_coverage"] == round((0.5 + 0.25 + 0.75) / 3, 4)
    assert agg["answered_rate"] == 0.5
    assert agg["by_tool"]["document_qa"]["count"] == 2
    assert agg["by_tool"]["review_code"]["mean_findings_count"] == 3.0
    # booleans are excluded from numeric means
    assert "mean_language_match" not in agg["by_tool"]["review_code"]


def test_document_qa_uses_shared_store(settings):
    """Regression: the evaluator must index into the same store the tool reads."""
    ctx = build_context(settings)
    sample = EvalSample.from_dict(
        {
            "question": "What transports are supported?",
            "reference": "streamable-http and stdio",
            "reference_contexts": ["The server supports streamable-http and stdio transports."],
        }
    )
    result = asyncio.run(evaluate_sample(ctx, sample))
    assert result["error"] is None
    assert result["metrics"]["citation_count"] > 0
    assert result["metrics"]["keyword_coverage"] > 0


def test_review_code_detects_expected_rules(settings):
    ctx = build_context(settings)
    sample = EvalSample.from_dict(
        {
            "tool": "review_code",
            "question": "Review",
            "input": {
                "language": "python",
                "source": "def run(cmd, opts=[]):\n    try:\n        return eval(cmd)\n    except:\n        return opts\n",
            },
            "metadata": {
                "expected_language": "python",
                "expected_rules": ["dangerous-call", "bare-except", "mutable-default"],
            },
        }
    )
    result = asyncio.run(evaluate_sample(ctx, sample))
    assert result["error"] is None
    assert result["metrics"]["language_match"] is True
    assert result["metrics"]["rules_matched"] == 1.0


def test_analyze_data_matches_shape(settings):
    ctx = build_context(settings)
    sample = EvalSample.from_dict(
        {
            "tool": "analyze_data",
            "question": "Profile",
            "input": {"source": "name,age,city\nAda,36,London\nGrace,45,NY\n"},
            "metadata": {"expected_rows": 2, "expected_columns": ["name", "age", "city"]},
        }
    )
    result = asyncio.run(evaluate_sample(ctx, sample))
    assert result["error"] is None
    assert result["metrics"]["rows_match"] is True
    assert result["metrics"]["columns_match"] is True


def test_unknown_tool_reports_error(settings):
    ctx = build_context(settings)
    sample = EvalSample.from_dict({"question": "Q", "tool": "does_not_exist"})
    result = asyncio.run(evaluate_sample(ctx, sample))
    assert result["error"] == "unknown tool: does_not_exist"


def test_per_tool_evaluator_runs_mixed_samples(settings):
    ctx = build_context(settings)
    samples = [
        EvalSample.from_dict(
            {
                "question": "Which tools exist?",
                "reference": "review_code and analyze_data",
                "reference_contexts": ["Tools include review_code and analyze_data."],
            }
        ),
        EvalSample.from_dict(
            {
                "tool": "review_code",
                "question": "Review",
                "input": {"source": "def f(x=[]):\n    pass\n", "language": "python"},
                "metadata": {"expected_rules": ["mutable-default"]},
            }
        ),
    ]
    report = asyncio.run(PerToolEvaluator(ctx).run(samples))

    assert report["aggregate"]["count"] == 2
    assert report["aggregate"]["error_count"] == 0
    assert set(report["aggregate"]["by_tool"]) == {"document_qa", "review_code"}
    assert report["aggregate"]["mean_keyword_coverage"] > 0
