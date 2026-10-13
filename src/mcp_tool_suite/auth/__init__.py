"""OAuth 2.1 provider for the MCP tool suite.

Layers:
- ``store``      SQLite persistence (clients, users, codes, refresh tokens)
- ``tokens``     RS256 JWT (audience-bound per RFC 8707), PKCE, PBKDF2 helpers
- ``routes``     authorization-server endpoints (RFC 8414/7591/7636/9728)
- ``middleware`` resource-server guard for the ``/mcp`` endpoint

The deployment is monolithic: the authorization server and the MCP resource
server share one origin, which keeps client configuration trivial while still
demonstrating a standards-compliant OAuth 2.1 flow.
"""

from __future__ import annotations

from pathlib import Path

from mcp_tool_suite.auth.bearer import BearerAuthMiddleware
from mcp_tool_suite.auth.middleware import OAuth2ResourceServerMiddleware
from mcp_tool_suite.auth.routes import OAuthContext, build_auth_routes
from mcp_tool_suite.auth.store import OAuthStore
from mcp_tool_suite.auth.tokens import load_or_create_keys


class OAuth2Server:
    """Facade wiring keys + store + endpoints + middleware for the ASGI app."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        issuer: str,
        resource_url: str,
        token_ttl: int = 3600,
        refresh_ttl: int | None = 2592000,
        demo_user: str | None = None,
        demo_password: str | None = None,
    ) -> None:
        data_dir = Path(data_dir)
        self.private_key, self.public_key = load_or_create_keys(data_dir)
        self.issuer = issuer
        self.resource_url = resource_url
        self.store = OAuthStore(
            data_dir / "oauth.db",
            demo_user=demo_user,
            demo_password=demo_password,
        )
        self.ctx = OAuthContext(
            store=self.store,
            private_key=self.private_key,
            public_key=self.public_key,
            issuer=issuer,
            resource_url=resource_url,
            token_ttl=token_ttl,
            refresh_ttl=refresh_ttl,
        )
        self.routes = build_auth_routes(self.ctx)

    def resource_middleware(self, app, guard_path: str) -> OAuth2ResourceServerMiddleware:
        return OAuth2ResourceServerMiddleware(
            app,
            public_key=self.public_key,
            issuer=self.issuer,
            resource_url=self.resource_url,
            guard_path=guard_path,
        )

    @staticmethod
    def bootstrap(
        *,
        data_dir: str | Path,
        issuer: str,
        resource_url: str,
        token_ttl: int = 3600,
        refresh_ttl: int | None = 2592000,
        demo_user: str | None = None,
        demo_password: str | None = None,
    ) -> "OAuth2Server":
        return OAuth2Server(
            data_dir=data_dir,
            issuer=issuer,
            resource_url=resource_url,
            token_ttl=token_ttl,
            refresh_ttl=refresh_ttl,
            demo_user=demo_user,
            demo_password=demo_password,
        )

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "OAuth2Server":
        return self

    def __exit__(self, *exc) -> None:
        self.close()