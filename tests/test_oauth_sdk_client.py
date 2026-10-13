"""Integration test: the MCP SDK's own OAuth client authenticates against our AS.

Unlike ``test_oauth_flow.py`` (which drives the endpoints by hand), this runs the
real ``OAuthClientProvider`` from the MCP SDK against a live server, proving a
standard MCP client can auto-discover, dynamically register, run PKCE, exchange
tokens and then call the server — with no bespoke client code.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from mcp_tool_suite.config import Settings
from mcp_tool_suite.server import build_http_app

REDIRECT_URI = "http://localhost/callback"


class InMemoryStorage(TokenStorage):
    """Minimal TokenStorage the provider persists client info + tokens into."""

    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def live_server(tmp_path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    settings = Settings(
        llm_provider="fake",
        embed_provider="hashing",
        web_search_provider="none",
        data_dir=str(tmp_path / "index"),
        auth_mode="oauth2",
        public_base_url=base,
        host="127.0.0.1",
        port=port,
        stateless_http=True,
        oauth_demo_user="admin",
        oauth_demo_password="admin",
    )
    app = build_http_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "server failed to start"
    try:
        yield base, settings
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def _drive(base: str, settings: Settings):
    resource = f"{base}/mcp"
    storage = InMemoryStorage()
    captured: dict[str, str] = {}

    async def redirect_handler(authorization_url: str) -> None:
        # Stand in for the browser + local callback server: submit the consent form
        # with demo credentials and pull the code out of the redirect.
        query = dict(httpx2.URL(authorization_url).params)
        async with httpx2.AsyncClient() as http:
            response = await http.post(
                authorization_url.split("?")[0],
                data={
                    **query,
                    "username": settings.oauth_demo_user,
                    "password": settings.oauth_demo_password,
                },
            )
        location = httpx2.URL(response.headers["location"])
        captured["code"] = location.params["code"]
        captured["state"] = location.params.get("state", "")

    async def callback_handler() -> AuthorizationCodeResult:
        return AuthorizationCodeResult(code=captured["code"], state=captured["state"])

    metadata = OAuthClientMetadata(
        client_name="sdk-native-test",
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope="mcp",
    )
    provider = OAuthClientProvider(
        resource,
        metadata,
        storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    async with httpx2.AsyncClient(auth=provider) as http_client:
        async with streamable_http_client(resource, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                info = await session.initialize()
                tools = await session.list_tools()
    return storage, info, tools


def test_sdk_oauth_client_end_to_end(live_server):
    base, settings = live_server

    storage, info, tools = asyncio.run(_drive(base, settings))

    assert info.server_info.name == settings.server_name
    assert len(tools.tools) == 8
    assert storage.tokens is not None
    assert storage.tokens.access_token.count(".") == 2  # a JWT
    assert storage.client_info is not None