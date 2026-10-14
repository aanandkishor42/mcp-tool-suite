"""Per-tool evaluators: invoke each MCP tool and compute offline quality signals.

Each evaluator is a small async function ``(ctx, sample) -> result``. The result
is a dict with ``output`` (a trimmed view of the tool's return value) and
``metrics`` (tool-specific numeric/boolean signals). Everything here runs with
the ``fake`` LLM, ``hashing`` embeddings and ``none`` search provider, so the
harness stays fully offline and deterministic in CI.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from evals.testset import EvalSample
from mcp_tool_suite.context import AppContext
from mcp_tool_suite.services.documents import chunk_text
from mcp_tool_suite.tools import (
    AnalyzeDataTool,
    AnalyzeDocumentTool,
    DocumentQaTool,
    EmailAssistantTool,
    GenerateReportTool,
    ReviewCodeTool,
    SemanticSearchTool,
    UsageStatsTool,
    WebResearchTool,
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_\-]+")


class OfflineMetrics:
    """Dependency-free scoring helpers reused across tool evaluators."""

    @staticmethod
    def keyword_coverage(reference: str, text: str) -> float:
        if not reference or not text:
            return 0.0
        ref_terms = {t for t in _WORD_RE.findall(reference.lower()) if len(t) > 3}
        if not ref_terms:
            return 0.0
        lowered = text.lower()
        hits = sum(1 for term in ref_terms if term in lowered)
        return round(hits / len(ref_terms), 4)

    @staticmethod
    def ratio_matched(text: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        lowered = text.lower()
        hits = sum(1 for term in terms if term.lower() in lowered)
        return round(hits / len(terms), 4)

    @staticmethod
    def set_ratio(expected: list[str], found: set[str]) -> float:
        if not expected:
            return 0.0
        return round(sum(1 for item in expected if item in found) / len(expected), 4)

    @staticmethod
    def has_answer(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return not any(
            phrase in lowered
            for phrase in (
                "i don't know",
                "no relevant",
                "not enough context",
                "no documents are indexed",
                "no search results",
                "no context available",
            )
        )


def _stable_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _source(sample: EvalSample) -> str:
    """Resolve the text/file/url argument for single-source tools."""
    return str(sample.input.get("source") or sample.source or sample.question)


def _top_k(sample: EvalSample) -> int:
    return int(sample.input.get("top_k", 4))


async def _index_text(ctx: AppContext, collection: str, source: str, text: str) -> None:
    chunks = chunk_text(
        text, size=ctx.settings.chunk_size, overlap=ctx.settings.chunk_overlap
    )
    if not chunks:
        return
    vectors = await ctx.embedder.embed(chunks)
    base = ctx.store.count(collection)
    ids = [f"{collection}-{base + i}" for i in range(len(chunks))]
    metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]
    ctx.store.add(
        collection, ids=ids, vectors=vectors, texts=chunks, metadatas=metadatas
    )


async def index_sample(ctx: AppContext, sample: EvalSample) -> None:
    """Index a RAG sample into the *shared* context store (the tools read this)."""
    if sample.source:
        await ctx.rag.index(sample.collection, sample.source)
        return
    if sample.reference_contexts:
        text = "\n\n".join(sample.reference_contexts)
        await _index_text(ctx, sample.collection, f"eval-{_stable_id(sample.question)}", text)


# --------------------------------------------------------------------------- #
# Per-tool evaluators
# --------------------------------------------------------------------------- #
async def evaluate_document_qa(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    await index_sample(ctx, sample)
    tool = DocumentQaTool().create(ctx)
    out = await tool(question=sample.question, collection=sample.collection, top_k=_top_k(sample))
    answer = out.get("answer", "")
    citations = out.get("citations", [])
    return {
        "output": {"answer": answer, "citations": citations},
        "metrics": {
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, answer),
            "has_answer": OfflineMetrics.has_answer(answer),
            "citation_count": len(citations),
        },
    }


async def evaluate_semantic_search(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    await index_sample(ctx, sample)
    tool = SemanticSearchTool().create(ctx)
    hits = await tool(query=sample.question, collection=sample.collection, top_k=_top_k(sample))
    target = sample.reference or " ".join(sample.reference_contexts)
    joined = " ".join(str(hit.get("text", "")) for hit in hits)
    return {
        "output": {
            "hits": [
                {"id": hit.get("id"), "score": hit.get("score"), "source": hit.get("source")}
                for hit in hits
            ]
        },
        "metrics": {
            "hit_count": len(hits),
            "keyword_coverage": OfflineMetrics.keyword_coverage(target, joined),
        },
    }


async def evaluate_analyze_document(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    tool = AnalyzeDocumentTool().create(ctx)
    out = await tool(source=_source(sample))
    analysis = out.get("analysis", "")
    return {
        "output": {"characters": out.get("characters", 0), "truncated": out.get("truncated", False)},
        "metrics": {
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, analysis),
            "characters": out.get("characters", 0),
        },
    }


async def evaluate_review_code(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    tool = ReviewCodeTool().create(ctx)
    out = await tool(
        source=_source(sample), language=str(sample.input.get("language", "auto"))
    )
    report = out.get("static_analysis") or {}
    findings = report.get("findings", [])
    rules = {str(f.get("rule")) for f in findings}
    expected_rules = [str(r) for r in sample.metadata.get("expected_rules", [])]
    expected_language = sample.metadata.get("expected_language")
    return {
        "output": {"language": out.get("language"), "findings": findings},
        "metrics": {
            "findings_count": len(findings),
            "language_match": (
                out.get("language") == expected_language if expected_language else None
            ),
            "rules_matched": (
                OfflineMetrics.set_ratio(expected_rules, rules) if expected_rules else None
            ),
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, out.get("review", "")),
        },
    }


async def evaluate_analyze_data(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    tool = AnalyzeDataTool().create(ctx)
    out = await tool(
        source=_source(sample), question=str(sample.input.get("question", ""))
    )
    columns = list(out.get("columns", []))
    expected_rows = sample.metadata.get("expected_rows")
    expected_columns = sample.metadata.get("expected_columns")
    return {
        "output": {"rows": out.get("rows", 0), "columns": columns},
        "metrics": {
            "rows": out.get("rows", 0),
            "rows_match": (
                out.get("rows") == expected_rows if expected_rows is not None else None
            ),
            "columns_match": (
                set(map(str, expected_columns)) == set(map(str, columns))
                if expected_columns
                else None
            ),
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, out.get("insights", "")),
        },
    }


async def evaluate_web_research(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    tool = WebResearchTool().create(ctx)
    out = await tool(
        query=sample.question, max_sources=int(sample.input.get("max_sources", 5))
    )
    sources = out.get("sources", [])
    min_sources = int(sample.metadata.get("min_sources", 0))
    return {
        "output": {"source_count": len(sources), "summary": out.get("summary", "")},
        "metrics": {
            "source_count": len(sources),
            "min_sources_met": len(sources) >= min_sources,
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, out.get("summary", "")),
        },
    }


async def evaluate_generate_report(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    await index_sample(ctx, sample)
    tool = GenerateReportTool().create(ctx)
    out = await tool(
        topic=sample.question,
        collection=sample.collection,
        sources=str(sample.input.get("sources", "")),
        max_words=int(sample.input.get("max_words", 600)),
    )
    sources_used = out.get("sources_used", 0)
    min_sources = int(sample.metadata.get("min_sources", 0))
    return {
        "output": {"sources_used": sources_used},
        "metrics": {
            "sources_used": sources_used,
            "min_sources_met": sources_used >= min_sources,
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, out.get("report", "")),
        },
    }


async def evaluate_email_assistant(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    tool = EmailAssistantTool().create(ctx)
    action = str(sample.input.get("action", "extract_actions"))
    out = await tool(
        source=_source(sample),
        action=action,
        instruction=str(sample.input.get("instruction", "")),
        recipient=str(sample.input.get("recipient", "")),
        tone=str(sample.input.get("tone", "professional")),
    )
    messages = out.get("messages", [])
    items = out.get("action_items", [])
    found = " ".join(str(item.get("text", "")) for item in items)
    expected = [str(x) for x in sample.metadata.get("expected_action_items", [])]
    return {
        "output": {
            "action": out.get("action"),
            "message_count": len(messages),
            "action_item_count": len(items),
            "subject": out.get("subject"),
        },
        "metrics": {
            "message_count": len(messages),
            "action_item_count": len(items),
            "keyword_coverage": OfflineMetrics.keyword_coverage(sample.reference, out.get("summary", "")),
            "action_items_matched": (
                OfflineMetrics.ratio_matched(found, expected) if expected else None
            ),
        },
    }


async def evaluate_usage_stats(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    tool = UsageStatsTool().create(ctx)
    out = await tool()
    totals = out.get("totals", {})
    return {
        "output": {
            "tool_calls": totals.get("tool_calls", 0),
            "llm_calls": totals.get("llm_calls", 0),
            "estimated_cost_usd": totals.get("estimated_cost_usd", 0.0),
        },
        "metrics": {
            "has_totals": bool(totals),
            "llm_calls": totals.get("llm_calls", 0),
            "tool_calls": totals.get("tool_calls", 0),
            "estimated_cost_usd": totals.get("estimated_cost_usd", 0.0),
        },
    }


ToolEvaluator = Callable[[AppContext, EvalSample], Awaitable[dict[str, Any]]]

TOOL_EVALUATORS: dict[str, ToolEvaluator] = {
    "document_qa": evaluate_document_qa,
    "semantic_search": evaluate_semantic_search,
    "analyze_document": evaluate_analyze_document,
    "review_code": evaluate_review_code,
    "analyze_data": evaluate_analyze_data,
    "web_research": evaluate_web_research,
    "generate_report": evaluate_generate_report,
    "email_assistant": evaluate_email_assistant,
    "usage_stats": evaluate_usage_stats,
}


async def evaluate_sample(ctx: AppContext, sample: EvalSample) -> dict[str, Any]:
    """Run one sample through its tool and return a result record."""
    evaluator = TOOL_EVALUATORS.get(sample.tool)
    base: dict[str, Any] = {
        "tool": sample.tool,
        "question": sample.question,
        "reference": sample.reference,
        "error": None,
    }
    if evaluator is None:
        base["error"] = f"unknown tool: {sample.tool}"
        base["metrics"] = {}
        return base

    start = time.perf_counter()
    try:
        result = await evaluator(ctx, sample)
    except Exception as exc:  # a failing tool must not abort the whole run
        base["error"] = f"{type(exc).__name__}: {exc}"
        base["metrics"] = {}
        return base

    base.update(result)
    base["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return base
