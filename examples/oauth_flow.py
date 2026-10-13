"""End-to-end OAuth 2.1 demo against a running server.

Start the server with OAuth enabled, then run this script:

    $env:AUTH_MODE="oauth2"; $env:PUBLIC_BASE_URL="http://localhost:8000"; python run.py
    python examples/oauth_flow.py

It performs the whole MCP client journey by hand so every step is visible:
protected-resource discovery -> dynamic client registration -> PKCE authorization
-> token exchange -> authenticated MCP session -> tool call.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets

import httpx

BASE = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
RESOURCE = f"{BASE}/mcp"
REDIRECT = "http://localhost/callback"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as http:
        meta = (await http.get("/.well-known/oauth-protected-resource")).json()
        print("1. protected resource :", meta["resource"])
        print("   authorization server:", meta["authorization_servers"][0])

        reg = await http.post(
            "/oauth/register",
            json={
                "client_name": "oauth_flow example",
                "redirect_uris": [REDIRECT],
                "token_endpoint_auth_method": "none",
            },
        )
        client_id = reg.json()["client_id"]
        print("2. registered client   :", client_id)

        verifier, challenge = _pkce()
        authz = await http.post(
            "/oauth/authorize",
            data={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "demo-state",
                "username": os.environ.get("OAUTH_DEMO_USER", "admin"),
                "password": os.environ.get("OAUTH_DEMO_PASSWORD", "admin"),
                "scopes": "mcp",
            },
        )
        code = httpx.URL(authz.headers["location"]).params["code"]
        print("3. authorization code  :", code[:12] + "...")

        token = await http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        access_token = token.json()["access_token"]
        print("4. access token        :", access_token[:24] + "... (RS256, aud=resource)")

    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {access_token}"}) as http_client:
        async with streamable_http_client(RESOURCE, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                info = await session.initialize()
                tools = await session.list_tools()
                print("5. authenticated MCP   :", info.server_info.name, f"({len(tools.tools)} tools)")
                for tool in tools.tools:
                    print("     -", tool.name)


if __name__ == "__main__":
    asyncio.run(main())