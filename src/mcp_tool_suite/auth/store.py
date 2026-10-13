"""SQLite-backed OAuth store (clients, users, auth codes, refresh tokens)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from mcp_tool_suite.auth.tokens import hash_secret, random_token, verify_secret


@dataclass(frozen=True, slots=True)
class ClientRecord:
    client_id: str
    display_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str
    grant_types: list[str]
    scopes: list[str]
    has_secret: bool = False


@dataclass(frozen=True, slots=True)
class UserRecord:
    username: str
    password_hash: str
    display_name: str


@dataclass(frozen=True, slots=True)
class CodeRecord:
    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str]
    resource: str | None
    subject: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class RefreshRecord:
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: str | None
    subject: str
    expires_at: int | None


class OAuthStore:
    """Small, thread-safe wrapper over SQLite. Demo-grade persistence for a portfolio."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        demo_user: str | None = None,
        demo_password: str | None = None,
        code_ttl: int = 600,
    ) -> None:
        self.db_path = str(db_path)
        self.code_ttl = code_ttl
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_schema()
        if demo_user and demo_password:
            self.upsert_user(demo_user, demo_password, display_name="Demo User")

    # ---- schema ------------------------------------------------------------
    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                client_secret_hash TEXT,
                display_name TEXT,
                redirect_uris TEXT NOT NULL,
                token_endpoint_auth_method TEXT NOT NULL,
                grant_types TEXT NOT NULL,
                scopes TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                display_name TEXT
            );
            CREATE TABLE IF NOT EXISTS auth_codes (
                code TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                scopes TEXT NOT NULL,
                resource TEXT,
                subject TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                scopes TEXT NOT NULL,
                resource TEXT,
                subject TEXT,
                expires_at INTEGER,
                revoked INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self._conn.commit()

    # ---- clients -----------------------------------------------------------
    def create_client(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        display_name: str = "",
        redirect_uris: list[str],
        token_endpoint_auth_method: str = "none",
        grant_types: list[str],
        scopes: list[str],
    ) -> tuple[str, str | None]:
        """Create a client; returns (client_id, client_secret_raw)."""
        client_id = client_id or random_token(24)
        secret_hash = hash_secret(client_secret) if client_secret else None
        with self._lock:
            self._conn.execute(
                """INSERT INTO clients (client_id, client_secret_hash, display_name,
                   redirect_uris, token_endpoint_auth_method, grant_types, scopes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    client_id,
                    secret_hash,
                    display_name,
                    json.dumps(redirect_uris),
                    token_endpoint_auth_method,
                    json.dumps(grant_types),
                    json.dumps(scopes),
                    int(time.time()),
                ),
            )
            self._conn.commit()
        return client_id, client_secret

    def get_client(self, client_id: str) -> ClientRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        if not row:
            return None
        return ClientRecord(
            client_id=row["client_id"],
            display_name=row["display_name"],
            redirect_uris=json.loads(row["redirect_uris"]),
            token_endpoint_auth_method=row["token_endpoint_auth_method"],
            grant_types=json.loads(row["grant_types"]),
            scopes=json.loads(row["scopes"]),
            has_secret=bool(row["client_secret_hash"]),
        )

    def verify_client_secret(self, client_id: str, secret: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT client_secret_hash FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        if not row or not row[0] or not secret:
            return False
        return verify_secret(secret, row[0])

    # ---- users -------------------------------------------------------------
    def upsert_user(self, username: str, password: str, *, display_name: str = "") -> None:
        password_hash = hash_secret(password)
        with self._lock:
            self._conn.execute(
                """INSERT INTO users (username, password_hash, display_name)
                   VALUES (?, ?, ?)
                   ON CONFLICT(username) DO UPDATE SET
                       password_hash=excluded.password_hash,
                       display_name=excluded.display_name""",
                (username, password_hash, display_name),
            )
            self._conn.commit()

    def get_user(self, username: str) -> UserRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if not row:
            return None
        return UserRecord(
            username=row["username"],
            password_hash=row["password_hash"],
            display_name=row["display_name"] or row["username"],
        )

    # ---- auth codes --------------------------------------------------------
    def create_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scopes: list[str],
        resource: str | None,
        subject: str,
    ) -> str:
        code = random_token(32)
        with self._lock:
            self._conn.execute(
                """INSERT INTO auth_codes (code, client_id, redirect_uri, code_challenge,
                   scopes, resource, subject, expires_at, used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    code,
                    client_id,
                    redirect_uri,
                    code_challenge,
                    json.dumps(scopes),
                    resource,
                    subject,
                    int(time.time()) + self.code_ttl,
                ),
            )
            self._conn.commit()
        return code

    def consume_code(self, code: str) -> CodeRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM auth_codes WHERE code = ?", (code,)
            ).fetchone()
            if not row:
                return None
            if row["used"]:
                return None
            self._conn.execute("UPDATE auth_codes SET used = 1 WHERE code = ?", (code,))
            self._conn.commit()
        return CodeRecord(
            code=row["code"],
            client_id=row["client_id"],
            redirect_uri=row["redirect_uri"],
            code_challenge=row["code_challenge"],
            scopes=json.loads(row["scopes"]),
            resource=row["resource"],
            subject=row["subject"],
            expires_at=row["expires_at"],
        )

    # ---- refresh tokens ----------------------------------------------------
    def create_refresh(
        self, *, client_id: str, scopes: list[str], resource: str | None, subject: str, ttl_seconds: int | None
    ) -> str:
        raw = random_token(48)
        expires_at = int(time.time()) + ttl_seconds if ttl_seconds else None
        with self._lock:
            self._conn.execute(
                """INSERT INTO refresh_tokens (token_hash, client_id, scopes, resource,
                   subject, expires_at, revoked) VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    _token_hash(raw),
                    client_id,
                    json.dumps(scopes),
                    resource,
                    subject,
                    expires_at,
                ),
            )
            self._conn.commit()
        return raw

    def get_refresh(self, raw_token: str) -> tuple[RefreshRecord, bool]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (_token_hash(raw_token),)
            ).fetchone()
        if not row:
            raise KeyError("refresh token not found")
        record = RefreshRecord(
            token_hash=row["token_hash"],
            client_id=row["client_id"],
            scopes=json.loads(row["scopes"]),
            resource=row["resource"],
            subject=row["subject"],
            expires_at=row["expires_at"],
        )
        return record, bool(row["revoked"])

    def revoke_refresh(self, raw_token: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
                (_token_hash(raw_token),),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _token_hash(raw: str) -> str:
    from mcp_tool_suite.auth.tokens import digest

    return digest(raw)