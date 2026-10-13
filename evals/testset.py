from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EvalSample(BaseModel):
    """One test case for per-tool evaluation.

    ``tool`` selects the evaluator (defaults to ``document_qa`` for backwards
    compatibility with Q&A-only sample files). ``input`` carries that tool's
    arguments; ``question`` doubles as the prompt/topic when no explicit input
    is given. ``reference`` and ``metadata`` drive the offline metrics.
    """

    question: str = Field(..., min_length=1)
    reference: str = Field(default="")
    reference_contexts: list[str] = Field(default_factory=list)
    collection: str = Field(default="evals")
    source: str | None = Field(default=None)
    tool: str = Field(default="document_qa")
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalSample":
        return cls(
            question=data["question"].strip(),
            reference=(data.get("reference") or "").strip(),
            reference_contexts=[c for c in data.get("reference_contexts", []) if c],
            collection=data.get("collection", "evals"),
            source=data.get("source"),
            tool=(data.get("tool") or "document_qa").strip(),
            input=data.get("input") or {},
            metadata=data.get("metadata") or {},
        )


def load_eval_samples(path: Path) -> list[EvalSample]:
    if not path.exists():
        raise FileNotFoundError(f"Eval samples not found: {path}")
    items = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("questions", items.get("samples", []))
    if not isinstance(items, list):
        raise ValueError(f"Eval file must be a list of samples: {path}")
    samples: list[EvalSample] = []
    for item in items:
        try:
            samples.append(EvalSample.from_dict(item))
        except Exception:
            # Skip malformed lines in test data, not the harness
            continue
    return samples


def save_eval_results(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
