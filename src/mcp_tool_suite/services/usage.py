"""In-process usage and cost accounting for tool calls and LLM calls.

Two things are tracked:

* **Tool calls** — count, error count and total/average latency per tool.
* **LLM calls** — calls, estimated tokens and estimated USD cost per
  ``provider:model``. Token counts are estimated from character counts
  (``chars / 4``); costs come from a small default price table that can be
  overridden per active provider via settings.

Everything lives in memory for the process lifetime. ``TrackedLLMProvider`` is a
transparent wrapper around any ``LLMProvider`` so nothing else has to change.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from mcp_tool_suite.providers.base import ChatMessage, LLMProvider

# USD per 1,000 tokens: (input, output). Local/offline providers are free.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "openai": (0.00015, 0.0006),  # ~gpt-4o-mini
    "groq": (0.00005, 0.00008),  # ~llama-3.1-8b-instant
    "anthropic": (0.0008, 0.004),  # ~claude-3-5-haiku
    "ollama": (0.0, 0.0),
    "fake": (0.0, 0.0),
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class UsageTracker:
    """Accumulates tool-call and LLM-call statistics. Thread-safe."""

    def __init__(self, prices: dict[str, tuple[float, float]] | None = None) -> None:
        self._lock = Lock()
        self._prices = dict(prices or DEFAULT_PRICES)
        self.started_at = datetime.now(UTC).isoformat()
        self.tool_calls: dict[str, dict[str, Any]] = {}
        self.llm_calls: dict[str, dict[str, Any]] = {}
        self.totals: dict[str, Any] = {
            "tool_calls": 0,
            "tool_errors": 0,
            "llm_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
        }

    def set_prices(self, provider: str, input_per_1k: float, output_per_1k: float) -> None:
        with self._lock:
            self._prices[provider] = (input_per_1k, output_per_1k)

    def price_for(self, provider: str) -> tuple[float, float]:
        with self._lock:
            return self._prices.get(provider, (0.0, 0.0))

    def record_tool(self, name: str, *, duration_ms: float, ok: bool = True) -> None:
        with self._lock:
            entry = self.tool_calls.setdefault(
                name, {"count": 0, "errors": 0, "total_ms": 0.0}
            )
            entry["count"] += 1
            entry["total_ms"] += duration_ms
            if not ok:
                entry["errors"] += 1
            self.totals["tool_calls"] += 1
            if not ok:
                self.totals["tool_errors"] += 1

    def record_llm(
        self,
        provider: str,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        cost = self._cost(provider, input_tokens, output_tokens)
        key = f"{provider}:{model}"
        with self._lock:
            entry = self.llm_calls.setdefault(
                key,
                {
                    "provider": provider,
                    "model": model,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_ms": 0.0,
                    "estimated_cost_usd": 0.0,
                },
            )
            entry["calls"] += 1
            entry["input_tokens"] += input_tokens
            entry["output_tokens"] += output_tokens
            entry["total_ms"] += duration_ms
            entry["estimated_cost_usd"] = round(entry["estimated_cost_usd"] + cost, 6)
            self.totals["llm_calls"] += 1
            self.totals["input_tokens"] += input_tokens
            self.totals["output_tokens"] += output_tokens
            self.totals["estimated_cost_usd"] = round(
                self.totals["estimated_cost_usd"] + cost, 6
            )

    def _cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        input_price, output_price = self._prices.get(provider, (0.0, 0.0))
        return (input_tokens / 1000.0) * input_price + (output_tokens / 1000.0) * output_price

    def summary(self) -> dict[str, Any]:
        with self._lock:
            tools = {
                name: {
                    **entry,
                    "total_ms": round(entry["total_ms"], 2),
                    "avg_ms": round(entry["total_ms"] / entry["count"], 2)
                    if entry["count"]
                    else 0.0,
                }
                for name, entry in sorted(self.tool_calls.items())
            }
            llms = {key: dict(entry) for key, entry in sorted(self.llm_calls.items())}
            return {
                "started_at": self.started_at,
                "totals": dict(self.totals),
                "tools": tools,
                "llms": llms,
            }


class TrackedLLMProvider:
    """Wraps an ``LLMProvider`` and records token/cost usage on every call."""

    def __init__(self, inner: LLMProvider, tracker: UsageTracker) -> None:
        self._inner = inner
        self._tracker = tracker
        self.name = inner.name

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        prompt = "\n".join(message.content for message in messages)
        start = time.perf_counter()
        text = await self._inner.complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        resolved_model = model or getattr(self._inner, "default_model", "unknown")
        self._tracker.record_llm(
            self.name,
            resolved_model,
            input_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(text),
            duration_ms=elapsed_ms,
        )
        return text
