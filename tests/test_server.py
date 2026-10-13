from __future__ import annotations

from mcp_tool_suite.config import Settings
from mcp_tool_suite.server import build_http_app


def _settings(tmp_path, **overrides) -> Settings:
    base = dict(
        llm_provider="fake",
        embed_provider="hashing",
        data_dir=str(tmp_path / "index"),
        stateless_http=True,
    )
    base.update(overrides)
    return Settings(**base)


def test_health_reports_tools(tmp_path):
    from starlette.testclient import TestClient

    app = build_http_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "document_qa" in body["tools"]


def test_auth_blocks_without_token(tmp_path):
    from starlette.testclient import TestClient

    app = build_http_app(_settings(tmp_path, auth_mode="bearer", api_key="s3cret"))
    with TestClient(app) as client:
        blocked = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        allowed = client.post(
            "/mcp",
            headers={"Authorization": "Bearer s3cret"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert blocked.status_code == 401
    assert blocked.headers.get("www-authenticate", "").startswith("Bearer")
    assert allowed.status_code != 401
