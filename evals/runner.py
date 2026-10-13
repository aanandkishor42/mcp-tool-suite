from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from mcp_tool_suite.config import Settings, get_settings
from mcp_tool_suite.context import AppContext, build_context
from mcp_tool_suite.providers.router import build_embedder, build_llm
from mcp_tool_suite.services.rag import RagService
from mcp_tool_suite.services.vectorstore import InMemoryVectorStore
from mcp_tool_suite.tools.rag_tools import DocumentQaTool, SemanticSearchTool

from evals.testset import EvalSample, load_eval_samples


class OfflineMetrics:
    @staticmethod
    def keyword_coverage(reference: str, answer: str) -> float:
        if not reference or not answer:
            return 0.0
        ref_terms = [t.lower() for t in reference.split() if len(t) > 3]
        if not ref_terms:
            return 0.0
        ans_terms = answer.lower()
        hits = sum(1 for t in set(ref_terms) if t in ans_terms)
        return round(hits / max(1, len(set(ref_terms))), 4)

    @staticmethod
    def citation_count(citations: list[dict[str, Any]]) -> int:
        return len(citations)

    @staticmethod
    def has_answer(answer: str) -> bool:
        if not answer:
            return False
        s = answer.lower()
        return "i don't know" not in s and "no relevant" not in s and "not enough context" not in s


class PerToolEvaluator:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        self.llm = build_llm(self.settings)
        self.embedder = build_embedder(self.settings)
        self.store = InMemoryVectorStore(persist_dir=self.settings.data_dir)
        self.rag = RagService(self.settings, self.llm, self.embedder, self.store)

    async def index_sample(self, sample: EvalSample) -> None:
        if sample.source:
            await self.rag.index(sample.collection, sample.source)
            return
        # Fallback: if no source, try to use reference_contexts concatenated
        if sample.reference_contexts:
            text = "\n\n".join(sample.reference_contexts)
            await self.index_text(sample.collection, f"eval-{hash(sample.question)}", text)

    async def index_text(self, collection: str, source: str, text: str) -> None:
        from mcp_tool_suite.services.documents import chunk_text

        chunks = chunk_text(
            text,
            size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        if not chunks:
            return
        vectors = await self.embedder.embed(chunks)
        ids = [f"{collection}-{self.store.count(collection) + i}" for i in range(len(chunks))]
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]
        self.store.add(collection, ids=ids, vectors=vectors, texts=chunks, metadatas=metadatas)

    async def evaluate_document_qa(self, samples: list[EvalSample]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        tool = DocumentQaTool().create(self.ctx)
        for s in samples:
            await self.index_sample(s)
            try:
                res = await tool(question=s.question, collection=s.collection, top_k=4)
                results.append(
                    {
                        "tool": "document_qa",
                        "question": s.question,
                        "reference": s.reference,
                        "answer": res.get("answer", ""),
                        "citations": res.get("citations", []),
                        "keyword_coverage": OfflineMetrics.keyword_coverage(s.reference, res.get("answer", "")),
                        "has_answer": OfflineMetrics.has_answer(res.get("answer", "")),
                        "citation_count": OfflineMetrics.citation_count(res.get("citations", [])),
                        "latency_ms": 0,
                    }
                )
            except Exception as exc:  # pragma: no cover
                results.append(
                    {
                        "tool": "document_qa",
                        "question": s.question,
                        "error": str(exc),
                    }
                )
        return results

    async def evaluate_semantic_search(self, samples: list[EvalSample]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        tool = SemanticSearchTool().create(self.ctx)
        for s in samples:
            await self.index_sample(s)
            try:
                res = await tool(query=s.question, collection=s.collection, top_k=4)
                results.append(
                    {
                        "tool": "semantic_search",
                        "question": s.question,
                        "hits": res.get("hits", []),
                        "hit_count": len(res.get("hits", [])),
                    }
                )
            except Exception as exc:  # pragma: no cover
                results.append(
                    {
                        "tool": "semantic_search",
                        "question": s.question,
                        "error": str(exc),
                    }
                )
        return results

    async def run(self, samples: list[EvalSample]) -> dict[str, Any]:
        qa = await self.evaluate_document_qa(samples)
        return {
            "samples": qa,
            "aggregate": {
                "count": len([r for r in qa if "error" not in r]),
                "mean_keyword_coverage": round(
                    statistics.mean([r["keyword_coverage"] for r in qa if "keyword_coverage" in r]) or 0, 4
                ),
                "answered_rate": round(
                    sum(1 for r in qa if r.get("has_answer")) / max(1, len(qa)), 4
                ),
            },
        }
