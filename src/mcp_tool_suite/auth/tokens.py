"""JWT minting/verification (RS256) and secret hashing.

Tokens are **audience-bound** (RFC 8707): the ``aud`` claim is the MCP resource
URL, so a token minted by another service can never be accepted here (confused-deputy
protection). Keys are RSA, generated once and persisted under ``data_dir``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key

ALGORITHM = "RS256"
_PBKDF2_ITERATIONS = 120_000


# ---- RSA keys --------------------------------------------------------------
def load_or_create_keys(data_dir: Path, name: str = "jwt") -> tuple[bytes, bytes]:
    """Return (private_key_pem, public_key_pem), creating them if needed."""
    data_dir.mkdir(parents=True, exist_ok=True)
    private_path = data_dir / f"{name}.key.pem"
    public_path = data_dir / f"{name}.pub.pem"
    if not (private_path.exists() and public_path.exists()):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        private_path.write_bytes(private_pem)
        public_path.write_bytes(public_pem)
    return private_path.read_bytes(), public_path.read_bytes()


def public_key_kid(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


def load_public_key(public_key: bytes):
    return load_pem_public_key(public_key)


# ---- JWT -------------------------------------------------------------------
def mint_jwt(
    private_key: bytes,
    *,
    issuer: str,
    audience: str,
    subject: str,
    client_id: str,
    scopes: list[str],
    ttl_seconds: int,
) -> tuple[str, dict]:
    """Return (jwt, claims). The token's ``aud`` is bound to *audience* (RFC 8707)."""
    now = datetime.now(timezone.utc)
    claims = {
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "sub": subject,
        "client_id": client_id,
        "scope": " ".join(scopes),
    }
    kid = public_key_kid(public_key_from_private(private_key))
    token = jwt.encode(claims, private_key, algorithm=ALGORITHM, headers={"kid": kid})
    return token, claims


def public_key_from_private(private_key: bytes) -> bytes:
    key = serialization.load_pem_private_key(private_key, password=None)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def verify_jwt(public_key: bytes, token: str, *, issuer: str, audience: str) -> dict:
    """Verify signature, issuer and audience; raise ``jwt`` exceptions on failure."""
    return jwt.decode(
        token,
        public_key,
        algorithms=[ALGORITHM],
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "iat", "sub", "aud", "iss"]},
    )


def build_jwks(public_key: bytes) -> dict:
    key = load_public_key(public_key)
    numbers = key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": ALGORITHM,
                "kid": public_key_kid(public_key),
                "n": _b64u_int(numbers.n),
                "e": _b64u_int(numbers.e),
            }
        ]
    }


def _b64u_int(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()


# ---- PKCE (RFC 7636) -------------------------------------------------------
def s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---- Secrets / passwords ---------------------------------------------------
def hash_secret(secret: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return f"$pbkdf2-sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_secret(secret: str, stored: str) -> bool:
    try:
        _, _, iterations, salt, expected_hex = stored.split("$", 4)
        digest = hashlib.pbkdf2_hmac(
            "sha256", secret.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        )
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


def random_token(nbytes: int = 48) -> str:
    return secrets.token_urlsafe(nbytes)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()