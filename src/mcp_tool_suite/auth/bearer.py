"""Bearer-token authentication middleware (ASGI level, SSE-safe).

This is the lightweight ``auth_mode="bearer"`` option: a single static API key
compared in constant time. For real deployments use ``auth_mode="oauth2"`` (see
``mcp_tool_suite.auth`` for the full OAuth 2.1 resource-server implementation).
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]

_JSON = b'{"error":"unauthorized","detail":"Missing or invalid bearer token"}'


class BearerAuthMiddleware:
    """Pure ASGI middleware so streaming (SSE) responses are never buffered."""

    def __init__(self, app: ASGIApp, *, api_key: str | None, protected_path: str = "/mcp") -> None:
        self.app = app
        self.api_key = api_key
        self.protected_path = protected_path.rstrip("/") or protected_path

    async def __call__(self, scope: Scope, receive, send) -> None:
        if scope["type"] != "http" or not self._is_protected(scope):
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":  # let CORS preflight through
            await self.app(scope, receive, send)
            return

        token = self._extract_token(scope)
        if not self.api_key or not token or not hmac.compare_digest(token, self.api_key):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b'Bearer realm="mcp"'),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _JSON})
            return

        await self.app(scope, receive, send)

    def _is_protected(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        return path == self.protected_path or path.startswith(self.protected_path + "/")

    @staticmethod
    def _extract_token(scope: Scope) -> str:
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                header = value.decode("latin-1")
                if header.lower().startswith("bearer "):
                    return header[7:].strip()
        return ""
