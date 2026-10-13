from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from mcp_tool_suite.auth import tokens
from mcp_tool_suite.config import Settings
from mcp_tool_suite.server import build_http_app

ISSUER = "http://testserver"
RESOURCE = "http://testserver/mcp"
REDIRECT = "http://client.example/callback"


def _app(tmp_path, **overrides):
    from starlette.testclient import TestClient

    base = dict(
        llm_provider="fake",
        embed_provider="hashing",
        data_dir=str(tmp_path / "index"),
        auth_mode="oauth2",
        public_base_url=ISSUER,
        stateless_http=True,
    )
    base.update(overrides)
    app = build_http_app(Settings(**base))
    return app, TestClient(app, base_url=ISSUER)


def _register(client) -> str:
    response = client.post(
        "/oauth/register",
        json={
            "client_name": "Test Client",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def _obtain_code(client, client_id: str, verifier: str, challenge: str) -> str:
    form = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "username": "admin",
        "password": "admin",
        "scopes": "mcp",
    }
    response = client.post("/oauth/authorize", data=form, follow_redirects=False)
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    query = parse_qs(urlsplit(location).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


def _token_flow(client, client_id: str) -> dict:
    verifier = tokens.random_token(32)
    code = _obtain_code(client, client_id, verifier, tokens.s256_challenge(verifier))
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_metadata_documents(tmp_path):
    _, client = _app(tmp_path)
    with client:
        prm = client.get("/.well-known/oauth-protected-resource").json()
        assert prm["resource"] == RESOURCE
        assert prm["authorization_servers"] == [ISSUER]

        asm = client.get("/.well-known/oauth-authorization-server").json()
        assert asm["issuer"] == ISSUER
        assert asm["authorization_endpoint"] == f"{ISSUER}/oauth/authorize"
        assert asm["token_endpoint"] == f"{ISSUER}/oauth/token"
        assert asm["code_challenge_methods_supported"] == ["S256"]


def test_mcp_requires_token(tmp_path):
    _, client = _app(tmp_path)
    with client:
        blocked = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert blocked.status_code == 401
    assert "resource_metadata" in blocked.headers["www-authenticate"]


def test_full_authorization_code_flow(tmp_path):
    _, client = _app(tmp_path)
    with client:
        client_id = _register(client)
        token_response = _token_flow(client, client_id)
        assert token_response["token_type"] == "Bearer"
        assert token_response["access_token"].count(".") == 2

        allowed = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token_response['access_token']}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert allowed.status_code != 401


def test_wrong_audience_token_rejected(tmp_path):
    _, client = _app(tmp_path)
    with client:
        private, _ = tokens.load_or_create_keys(tmp_path / "index")
        foreign, _ = tokens.mint_jwt(
            private,
            issuer=ISSUER,
            audience="http://evil.example/mcp",
            subject="admin",
            client_id="attacker",
            scopes=["mcp"],
            ttl_seconds=60,
        )
        blocked = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {foreign}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert blocked.status_code == 401


def test_refresh_rotation(tmp_path):
    _, client = _app(tmp_path)
    with client:
        client_id = _register(client)
        first = _token_flow(client, client_id)

        refreshed = client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": first["refresh_token"],
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        new_tokens = refreshed.json()
        assert new_tokens["refresh_token"] != first["refresh_token"]

        replay = client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": first["refresh_token"],
            },
        )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_pkce_verification_failure(tmp_path):
    _, client = _app(tmp_path)
    with client:
        client_id = _register(client)
        code = _obtain_code(client, client_id, "verifier", tokens.s256_challenge("verifier"))
        response = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": client_id,
                "code_verifier": "a-different-verifier",
            },
        )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"