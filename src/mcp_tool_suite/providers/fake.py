"""A deterministic offline provider so the suite (and its tests) run with no keys."""

from __future__ import annotations

from typing import Sequence

from mcp_tool_suite.providers.base import ChatMessage


class FakeLLMProvider:
    """Echoes a bounded view of the prompt. Useful for tests and dry runs."""

    name = "fake"

    def __init__(self, default_model: str = "fake") -> None:
        self.default_model = default_model

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return f"[fake:{model or self.default_model}] {last_user.strip()[:280]}"
