"""Convenience launcher: ``python run.py`` (uses settings for transport)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp_tool_suite.server import main  # noqa: E402

if __name__ == "__main__":
    main()
