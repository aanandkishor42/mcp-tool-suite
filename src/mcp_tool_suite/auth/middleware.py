"""Resource-server ASGI middleware protecting the MCP streamable endpoint."""

from __future__ import annotations

import json

import jwt

from mcp_tool_suite.auth.tokens import verify_jwt


class OAuth2ResourceServerMiddleware:
    """Validates a Bearer JWT against the resource server's JWKS and audience.

    Only guards ``guard_path``. All other paths pass through untouched, so the
    authorization server endpoints stay public.
    """

    def __init__(self, app, *, public_key, issuer: str, resource_url: str, guard_path: str) -> None:
        self.app = app
        self.public_key = public_key
        self.issuer = issuer
        self.resource_url = resource_url
        self.guard_path = guard_path

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self._is_guarded(scope.get("path", self.guard_path)):
            await self.app(scope, receive, send)
            return
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        authorization = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                authorization = value.decode("latin-1")
                break

        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not token:
            await self._reject(send, "invalid_request", "No bearer token provided")
            return

        try:
            claims = verify_jwt(
                self.public_key,
                token,
                issuer=self.issuer,
                audience=self.resource_url,
            )
        except jwt.InvalidTokenError:
            await self._reject(send, "invalid_token", "The access token is invalid or expired")
            return
        if "mcp" not in (claims.get("scope") or "").split():
            await self._reject(send, "insufficient_scope", "The token lacks the 'mcp' scope")
            return

        scope.setdefault("state", {})["oauth"] = claims
        await self.app(scope, receive, send)

    def _is_guarded(self, path: str) -> bool:
        path = path.rstrip("/") or "/"
        return path == self.guard_path.rstrip("/") or path.startswith(self.guard_path.rstrip("/") + "/")

    async def _reject(self, send, error: str, description: str) -> None:
        body = json.dumps({"error": error, "error_description": description}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"cache-control", b"no-store"),
            (
                b"www-authenticate",
                (
                    f'Bearer error="{error}", '
                    f'error_description="{description}", '
                    f'resource_metadata="{self.issuer}/.well-known/oauth-protected-resource"'
                ).encode(),
            ),
        ]
        await send({"type": "http.response.start", "status": 401, "headers": headers})
        await send({"type": "http.response.body", "body": body})