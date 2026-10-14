"""Core provider contracts shared by every backend implementation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMProvider(Protocol):
    """A chat-completion backend. Implementations are interchangeable."""

    name: str

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:  # pragma: no cover - protocol
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into vectors. Implementations are interchangeable."""

    name: str
    dimension: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        ...
