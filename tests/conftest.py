from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_tool_suite.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        llm_provider="fake",
        embed_provider="hashing",
        web_search_provider="none",
        data_dir=str(tmp_path / "index"),
        auth_mode="none",
        stateless_http=True,
    )
