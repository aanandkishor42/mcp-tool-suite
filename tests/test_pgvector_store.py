from __future__ import annotations

import os

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("pgvector")

from mcp_tool_suite.services.pgvector_store import PgVectorStore

_DSN = os.environ.get("PGVECTOR_TEST_DSN")


def _store() -> PgVectorStore:
    if not _DSN:
        pytest.skip("set PGVECTOR_TEST_DSN to run pgvector tests")
    try:
        return PgVectorStore(dsn=_DSN, dimension=2, table="mcp_vectors_test")
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"pgvector unavailable: {exc}")


def test_add_and_search_returns_best_match():
    store = _store()
    collection = "pgtest_add"
    store.drop_collection(collection)
    try:
        store.add(
            collection,
            ids=["a", "b"],
            vectors=[[1.0, 0.0], [0.0, 1.0]],
            texts=["first", "second"],
            metadatas=[{"source": "x"}, {"source": "y"}],
        )
        hits = store.search(collection, [0.9, 0.1], top_k=1)
        assert len(hits) == 1
        assert hits[0].id == "a"
        assert hits[0].text == "first"
        assert hits[0].metadata["source"] == "x"
        assert store.count(collection) == 2
        assert store.has_collection(collection) is True
        assert collection in store.collections()
    finally:
        store.drop_collection(collection)


def test_upsert_replaces_existing_id():
    store = _store()
    collection = "pgtest_upsert"
    store.drop_collection(collection)
    try:
        store.add(collection, ids=["a"], vectors=[[1.0, 0.0]], texts=["old"])
        store.add(collection, ids=["a"], vectors=[[1.0, 0.0]], texts=["new"])
        assert store.count(collection) == 1
        assert store.search(collection, [1.0, 0.0])[0].text == "new"
    finally:
        store.drop_collection(collection)


def test_missing_collection_returns_empty():
    store = _store()
    assert store.search("pgtest_missing", [1.0, 0.0]) == []
    assert store.has_collection("pgtest_missing") is False
    assert store.count("pgtest_missing") == 0
