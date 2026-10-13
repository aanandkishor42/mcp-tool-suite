"""Anthropic (Claude) provider using the Messages API directly over HTTP."""

from __future__ import annotations

from typing import Sequence

import httpx

from mcp_tool_suite.providers.base import ChatMessage


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 60.0,
    ) -> None:
        self.name = "anthropic"
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        system_parts = [m.content for m in messages if m.role == "system"]
        chat = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        payload: dict[str, object] = {
            "model": model or self.default_model,
            "messages": chat,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/messages", headers=headers, json=payload
            )
            response.raise_for_status()
            data = response.json()
        return "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
