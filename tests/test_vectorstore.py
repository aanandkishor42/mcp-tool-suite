from __future__ import annotations

from mcp_tool_suite.services.vectorstore import InMemoryVectorStore


def test_add_and_search_returns_best_match():
    store = InMemoryVectorStore()
    store.add(
        "c",
        ids=["a", "b"],
        vectors=[[1.0, 0.0], [0.0, 1.0]],
        texts=["first", "second"],
        metadatas=[{"source": "x"}, {"source": "y"}],
    )
    hits = store.search("c", [0.9, 0.1], top_k=1)
    assert len(hits) == 1
    assert hits[0].id == "a"
    assert hits[0].metadata["source"] == "x"


def test_missing_collection_returns_empty():
    store = InMemoryVectorStore()
    assert store.search("nope", [1.0, 0.0]) == []
    assert store.has_collection("nope") is False


def test_persistence_roundtrip(tmp_path):
    store = InMemoryVectorStore(persist_dir=tmp_path)
    store.add("c", ids=["a"], vectors=[[1.0, 0.0]], texts=["first"])

    reloaded = InMemoryVectorStore(persist_dir=tmp_path)
    assert reloaded.count("c") == 1
    assert reloaded.search("c", [1.0, 0.0])[0].text == "first"
