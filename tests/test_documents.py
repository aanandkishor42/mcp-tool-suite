from __future__ import annotations

import asyncio

from mcp_tool_suite.services.documents import chunk_text, load_text


def test_chunk_text_splits_with_overlap():
    text = " ".join(f"word{i}" for i in range(300))
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert all(chunks)


def test_chunk_text_empty():
    assert chunk_text("   ") == []


def test_chunk_text_rejects_bad_overlap():
    import pytest

    with pytest.raises(ValueError):
        chunk_text("hello world", size=10, overlap=10)


def test_load_text_passes_through_raw_text():
    assert asyncio.run(load_text("just some raw text")) == "just some raw text"
