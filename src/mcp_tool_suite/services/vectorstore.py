"""A dependency-light in-memory vector store with optional disk persistence.

Kept intentionally simple (numpy cosine similarity) so the whole suite runs with
no external services. The ``VectorStore`` shape mirrors pgvector / Qdrant, so a
production backend can drop in later without touching callers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np


@dataclass(slots=True)
class Hit:
    id: str
    text: str
    score: float
    metadata: dict[str, object] = field(default_factory=dict)


class VectorStore(Protocol):
    def add(
        self,
        collection: str,
        *,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, object]] | None = None,
    ) -> None: ...

    def search(
        self, collection: str, query_vector: Sequence[float], *, top_k: int = 4
    ) -> list[Hit]: ...

    def has_collection(self, collection: str) -> bool: ...

    def count(self, collection: str) -> int: ...

    def collections(self) -> list[str]: ...


@dataclass(slots=True)
class _Collection:
    ids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    metadatas: list[dict[str, object]] = field(default_factory=list)
    matrix: np.ndarray | None = None  # (n, dim), L2-normalised rows


class InMemoryVectorStore:
    def __init__(self, persist_dir: str | Path | None = None) -> None:
        self._collections: dict[str, _Collection] = {}
        self._persist_dir = Path(persist_dir) if persist_dir else None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_all()

    # ---- writes -----------------------------------------------------------
    def add(
        self,
        collection: str,
        *,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, object]] | None = None,
    ) -> None:
        if not (len(ids) == len(vectors) == len(texts)):
            raise ValueError("ids, vectors and texts must be the same length")
        store = self._collections.setdefault(collection, _Collection())
        new_matrix = np.asarray(vectors, dtype=np.float32)
        if new_matrix.ndim != 2:
            raise ValueError("vectors must be a 2D array")
        new_matrix = _l2_normalize(new_matrix)

        store.ids.extend(ids)
        store.texts.extend(texts)
        store.metadatas.extend(metadatas or [{}] * len(ids))
        store.matrix = (
            new_matrix if store.matrix is None else np.vstack([store.matrix, new_matrix])
        )
        self._persist(collection)

    # ---- reads ------------------------------------------------------------
    def search(
        self, collection: str, query_vector: Sequence[float], *, top_k: int = 4
    ) -> list[Hit]:
        store = self._collections.get(collection)
        if not store or store.matrix is None or len(store.ids) == 0:
            return []
        query = _l2_normalize(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))
        similarities = (store.matrix @ query.T).reshape(-1)
        k = max(1, min(top_k, len(store.ids)))
        top_indices = np.argsort(-similarities)[:k]
        return [
            Hit(
                id=store.ids[i],
                text=store.texts[i],
                score=float(similarities[i]),
                metadata=store.metadatas[i],
            )
            for i in top_indices
        ]

    def has_collection(self, collection: str) -> bool:
        return collection in self._collections and len(self._collections[collection].ids) > 0

    def count(self, collection: str) -> int:
        store = self._collections.get(collection)
        return len(store.ids) if store else 0

    def collections(self) -> list[str]:
        return sorted(self._collections)

    # ---- persistence ------------------------------------------------------
    def _paths(self, collection: str) -> tuple[Path, Path]:
        assert self._persist_dir is not None
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in collection)
        return (
            self._persist_dir / f"{safe}.json",
            self._persist_dir / f"{safe}.npy",
        )

    def _persist(self, collection: str) -> None:
        if not self._persist_dir:
            return
        store = self._collections[collection]
        meta_path, vec_path = self._paths(collection)
        meta_path.write_text(
            json.dumps(
                {
                    "ids": store.ids,
                    "texts": store.texts,
                    "metadatas": store.metadatas,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if store.matrix is not None:
            np.save(vec_path, store.matrix)

    def _load_all(self) -> None:
        assert self._persist_dir is not None
        for meta_path in self._persist_dir.glob("*.json"):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            vec_path = meta_path.with_suffix(".npy")
            matrix = np.load(vec_path) if vec_path.exists() else None
            name = meta_path.stem
            self._collections[name] = _Collection(
                ids=data["ids"],
                texts=data["texts"],
                metadatas=data["metadatas"],
                matrix=matrix,
            )


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
