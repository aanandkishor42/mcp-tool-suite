from __future__ import annotations

import time

import pytest

from mcp_tool_suite.auth import tokens


def test_keys_are_persisted_and_stable(tmp_path):
    priv1, pub1 = tokens.load_or_create_keys(tmp_path)
    priv2, pub2 = tokens.load_or_create_keys(tmp_path)
    assert priv1 == priv2 and pub1 == pub2
    assert b"PRIVATE KEY" in priv1 and b"PUBLIC KEY" in pub1


def test_jwt_round_trip(tmp_path):
    priv, pub = tokens.load_or_create_keys(tmp_path)
    token, claims = tokens.mint_jwt(
        priv,
        issuer="https://as.example",
        audience="https://as.example/mcp",
        subject="admin",
        client_id="client-1",
        scopes=["mcp"],
        ttl_seconds=60,
    )
    verified = tokens.verify_jwt(pub, token, issuer="https://as.example", audience="https://as.example/mcp")
    assert verified["sub"] == "admin"
    assert verified["scope"] == "mcp"
    assert verified["client_id"] == "client-1"
    assert claims["exp"] > time.time()


def test_jwt_wrong_audience_rejected(tmp_path):
    import jwt

    priv, pub = tokens.load_or_create_keys(tmp_path)
    token, _ = tokens.mint_jwt(
        priv,
        issuer="https://as.example",
        audience="https://other.example/mcp",
        subject="admin",
        client_id="client-1",
        scopes=["mcp"],
        ttl_seconds=60,
    )
    with pytest.raises(jwt.InvalidTokenError):
        tokens.verify_jwt(pub, token, issuer="https://as.example", audience="https://as.example/mcp")


def test_jwt_expired_rejected(tmp_path):
    import jwt

    priv, pub = tokens.load_or_create_keys(tmp_path)
    token, _ = tokens.mint_jwt(
        priv,
        issuer="https://as.example",
        audience="https://as.example/mcp",
        subject="admin",
        client_id="client-1",
        scopes=["mcp"],
        ttl_seconds=-5,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        tokens.verify_jwt(pub, token, issuer="https://as.example", audience="https://as.example/mcp")


def test_jwks_matches_token_kid(tmp_path):
    import jwt

    priv, pub = tokens.load_or_create_keys(tmp_path)
    token, _ = tokens.mint_jwt(
        priv,
        issuer="https://as.example",
        audience="https://as.example/mcp",
        subject="admin",
        client_id="client-1",
        scopes=["mcp"],
        ttl_seconds=60,
    )
    kid = jwt.get_unverified_header(token)["kid"]
    jwks = tokens.build_jwks(pub)
    assert jwks["keys"][0]["kid"] == kid
    assert jwks["keys"][0]["kty"] == "RSA"
    assert jwks["keys"][0]["alg"] == "RS256"


def test_pkce_rfc7636_vector():
    # Appendix B of RFC 7636
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert tokens.s256_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_secret_hash_and_verify():
    stored = tokens.hash_secret("hunter2")
    assert stored.startswith("$pbkdf2-sha256$")
    assert tokens.verify_secret("hunter2", stored)
    assert not tokens.verify_secret("wrong", stored)
    assert not tokens.verify_secret("hunter2", "not-a-valid-hash")


def test_random_token_and_digest_are_deterministic():
    assert tokens.random_token() != tokens.random_token()
    assert tokens.digest("abc") == tokens.digest("abc")
    assert tokens.digest("abc") != tokens.digest("abd")