"""OAuth 2.1 endpoints for the MCP authorization server.

Implements the flows an MCP client expects, on the same origin as the resource
server: RFC 8414 AS metadata, RFC 9728 protected-resource metadata, dynamic
client registration (RFC 7591), authorization code + PKCE (RFC 7636), token
exchange, refresh rotation, revocation (RFC 7009) and a JSON web key set.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp_tool_suite.auth import tokens
from mcp_tool_suite.auth.store import OAuthStore
from mcp_tool_suite.auth.tokens import (
    mint_jwt,
    s256_challenge,
    verify_secret,
)

SUPPORTED_SCOPES = ["mcp"]
DEFAULT_SCOPES = ["mcp"]
VALID_RESPONSE_TYPES = ("code",)
VALID_GRANTS = ("authorization_code", "refresh_token")
VALID_AUTH_METHODS = ("none", "client_secret_post")


class OAuthError(Exception):
    def __init__(self, status: int, error: str, description: str = "") -> None:
        super().__init__(error)
        self.status = status
        self.error = error
        self.description = description


@dataclass(slots=True)
class OAuthContext:
    store: OAuthStore
    private_key: bytes
    public_key: bytes
    issuer: str
    resource_url: str
    token_ttl: int = 3600
    refresh_ttl: int | None = 2592000

    @property
    def origin(self) -> str:
        parsed = urlsplit(self.issuer)
        return f"{parsed.scheme}://{parsed.netloc}"


# ---- helpers ---------------------------------------------------------------
def _json_error(exc: OAuthError) -> JSONResponse:
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    return JSONResponse(body, status_code=exc.status)


async def _form(request: Request) -> dict[str, str]:
    try:
        form = await request.form()
    except Exception:
        raise OAuthError(400, "invalid_request", "Body must be form-encoded")
    return {key: (value if isinstance(value, str) else value.filename or "") for key, value in form.multi_items()}


def _authorize_request_error(params: dict[str, str]) -> str | None:
    if params.get("response_type") not in VALID_RESPONSE_TYPES:
        return 'response_type must be "code"'
    if not params.get("client_id"):
        return "client_id is required"
    if not params.get("redirect_uri"):
        return "redirect_uri is required"
    challenge = params.get("code_challenge")
    if not challenge or params.get("code_challenge_method", "S256").upper() != "S256":
        return "code_challenge (S256) is required (PKCE)"
    return None


def _authorize_form_html(
    ctx: OAuthContext,
    client,
    params: dict[str, str],
    *,
    error: str | None = None,
    scope_choices: list[str] | None = None,
    form_action: str = "/oauth/authorize",
) -> HTMLResponse:
    choices = scope_choices or ["mcp"]
    checked = " ".join(f'<label><input type="checkbox" name="scopes" value="{s}" checked> {s}</label><br>' for s in choices)
    error_html = f'<p style="color:#b00020">{error}</p>' if error else ""
    hidden = "".join(
        f'<input type="hidden" name="{key}" value="{value}">' for key, value in params.items() if value
    )
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Sign in - {ctx.issuer}</title>
<style>
 body {{ font-family: system-ui, sans-serif; background:#f5f7fa; display:grid; place-items:center; min-height:100vh; margin:0 }}
 .card {{ background:#fff; border:1px solid #e3e8ef; border-radius:12px; padding:32px; width:360px; box-shadow:0 8px 24px rgba(0,0,0,.06) }}
 h1 {{ font-size:20px; margin-top:0 }} .muted {{ color:#6b7280; font-size:13px }}
 input[type=text],input[type=password] {{ width:100%; padding:10px; margin:6px 0 14px; border:1px solid #d1d5db; border-radius:8px; box-sizing:border-box }}
 button {{ width:100%; padding:11px; background:#111827; color:#fff; border:0; border-radius:8px; font-size:15px; cursor:pointer }}
</style></head><body>
<div class="card">
  <h1>Sign in to {client.display_name or client.client_id}</h1>
  <p class="muted">This app is requesting access to <code>{ctx.resource_url}</code>.</p>
  {error_html}
  <form method="post" action="{form_action}">
    {hidden}
    <label for="username">Username</label>
    <input id="username" name="username" type="text" required autocomplete="username">
    <label for="password">Password</label>
    <input id="password" name="password" type="password" required autocomplete="current-password">
    <p class="muted">Scopes</p>{checked}
    <button type="submit">Authorize</button>
  </form>
</div></body></html>"""
    return HTMLResponse(page)


# ---- handlers --------------------------------------------------------------
async def metadata_authorization_server(request: Request) -> JSONResponse:
    ctx: OAuthContext = request.state.oauth
    return JSONResponse(
        {
            "issuer": ctx.issuer,
            "authorization_endpoint": f"{ctx.issuer}/oauth/authorize",
            "token_endpoint": f"{ctx.issuer}/oauth/token",
            "registration_endpoint": f"{ctx.issuer}/oauth/register",
            "revocation_endpoint": f"{ctx.issuer}/oauth/revoke",
            "jwks_uri": f"{ctx.issuer}/oauth/jwks.json",
            "response_types_supported": list(VALID_RESPONSE_TYPES),
            "grant_types_supported": list(VALID_GRANTS),
            "token_endpoint_auth_methods_supported": list(VALID_AUTH_METHODS),
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": SUPPORTED_SCOPES,
            "subject_types_supported": ["public"],
        }
    )


async def metadata_protected_resource(request: Request) -> JSONResponse:
    ctx: OAuthContext = request.state.oauth
    return JSONResponse(
        {
            "resource": ctx.resource_url,
            "authorization_servers": [ctx.issuer],
            "scopes_supported": SUPPORTED_SCOPES,
            "bearer_methods_supported": ["header"],
        }
    )


async def jwks(request: Request) -> JSONResponse:
    ctx: OAuthContext = request.state.oauth
    return JSONResponse(tokens.build_jwks(ctx.public_key))


async def register(request: Request) -> JSONResponse:
    ctx: OAuthContext = request.state.oauth
    try:
        body = await request.json()
    except Exception:
        raise OAuthError(400, "invalid_client_metadata", "Request body must be JSON")

    redirect_uris = body.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise OAuthError(400, "invalid_redirect_uri", "redirect_uris is required")
    for uri in redirect_uris:
        if not isinstance(uri, str) or urlsplit(uri).scheme not in ("http", "https") or not urlsplit(uri).netloc:
            raise OAuthError(400, "invalid_redirect_uri", f"Not a valid URI: {uri!r}")

    auth_method = body.get("token_endpoint_auth_method", "none")
    if auth_method not in VALID_AUTH_METHODS:
        raise OAuthError(400, "invalid_client_metadata", f"Unsupported token_endpoint_auth_method: {auth_method}")

    grant_types = body.get("grant_types") or ["authorization_code", "refresh_token"]
    scopes = body.get("scopes") or DEFAULT_SCOPES
    if any(s not in SUPPORTED_SCOPES for s in scopes):
        raise OAuthError(400, "invalid_client_metadata", f"Unsupported scopes: {scopes}")

    client_secret = None
    if auth_method != "none":
        client_secret = tokens.random_token(48)

    client_id, _ = ctx.store.create_client(
        client_id=None,
        client_secret=client_secret,
        display_name=body.get("client_name", ""),
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=auth_method,
        grant_types=grant_types,
        scopes=scopes,
    )
    response: dict[str, Any] = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "client_secret_expires_at": 0,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": auth_method,
        "grant_types": grant_types,
        "scopes": scopes,
    }
    if client_secret:
        response["client_secret"] = client_secret
    return JSONResponse(response, status_code=201)


async def authorize_get(request: Request) -> Response:
    ctx: OAuthContext = request.state.oauth
    params = dict(request.query_params)
    client = _validate_authorize(ctx, params, redirect_target=params.get("redirect_uri"))
    return _authorize_form_html(ctx, client, params)


async def authorize_post(request: Request) -> Response:
    ctx: OAuthContext = request.state.oauth
    form = await _form(request)
    params = {
        key: form[key]
        for key in ("response_type", "client_id", "redirect_uri", "code_challenge", "state")
        if key in form
    }
    client = _validate_authorize(ctx, params, redirect_target=None)

    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    user = ctx.store.get_user(username)
    if not user or not verify_secret(password, user.password_hash):
        return _authorize_form_html(ctx, client, params, error="Invalid username or password.")

    scopes = form.get("scopes") or DEFAULT_SCOPES
    if isinstance(scopes, str):
        scopes = [scopes]
    resource = params.get("resource") or ctx.resource_url
    code = ctx.store.create_code(
        client_id=client.client_id,
        redirect_uri=params["redirect_uri"],
        code_challenge=params["code_challenge"],
        scopes=[s for s in scopes if s in SUPPORTED_SCOPES],
        resource=resource,
        subject=user.username,
    )
    target = params["redirect_uri"]
    separator = "&" if "?" in target else "?"
    target = f"{target}{separator}code={code}"
    if params.get("state"):
        target += f"&state={params['state']}"
    return RedirectResponse(target, status_code=302)


async def token(request: Request) -> JSONResponse:
    ctx: OAuthContext = request.state.oauth
    form = await _form(request)
    grant_type = form.get("grant_type")

    if grant_type == "authorization_code":
        return await _token_auth_code(ctx, form)
    if grant_type == "refresh_token":
        return await _token_refresh(ctx, form)
    raise OAuthError(400, "unsupported_grant_type", "Unsupported grant_type")


async def revoke(request: Request) -> Response:
    ctx: OAuthContext = request.state.oauth
    form = await _form(request)
    candidate = form.get("token")
    if candidate:
        try:
            ctx.store.revoke_refresh(candidate)
        except KeyError:
            pass
    return Response(status_code=200)


# ---- token grant impls -----------------------------------------------------
def _client_for_token_request(ctx: OAuthContext, form: dict[str, str]):
    client_id = form.get("client_id")
    if not client_id:
        raise OAuthError(401, "invalid_client", "client_id is required")
    client = ctx.store.get_client(client_id)
    if not client:
        raise OAuthError(401, "invalid_client", "Unknown client_id")
    if client.token_endpoint_auth_method == "client_secret_post":
        if not ctx.store.verify_client_secret(client_id, form.get("client_secret", "")):
            raise OAuthError(401, "invalid_client", "Bad client credentials")
    return client


async def _token_auth_code(ctx: OAuthContext, form: dict[str, str]) -> JSONResponse:
    client = _client_for_token_request(ctx, form)

    code = form.get("code")
    record = ctx.store.consume_code(code) if code else None
    if not record:
        raise OAuthError(400, "invalid_grant", "Unknown or already-used authorization code")
    if record.client_id != client.client_id:
        raise OAuthError(400, "invalid_grant", "Code was issued to another client")
    if record.expires_at < time.time():
        raise OAuthError(400, "invalid_grant", "Authorization code expired")
    provided_redirect = form.get("redirect_uri")
    if provided_redirect and provided_redirect != record.redirect_uri:
        raise OAuthError(400, "invalid_grant", "redirect_uri mismatch")
    verifier = form.get("code_verifier")
    if not verifier or not _constant_time_eq(s256_challenge(verifier), record.code_challenge):
        raise OAuthError(400, "invalid_grant", "PKCE verification failed")

    resource = form.get("resource")
    if resource and record.resource and resource != record.resource:
        raise OAuthError(400, "invalid_target", "Token resource does not match the original request")
    audience = resource or record.resource or ctx.resource_url

    access, claims = mint_jwt(
        ctx.private_key,
        issuer=ctx.issuer,
        audience=audience,
        subject=record.subject,
        client_id=client.client_id,
        scopes=record.scopes,
        ttl_seconds=ctx.token_ttl,
    )
    refresh = ctx.store.create_refresh(
        client_id=client.client_id,
        scopes=record.scopes,
        resource=audience,
        subject=record.subject,
        ttl_seconds=ctx.refresh_ttl,
    )
    return _token_response(access, claims["exp"], refresh, record.scopes)


async def _token_refresh(ctx: OAuthContext, form: dict[str, str]) -> JSONResponse:
    client = _client_for_token_request(ctx, form)

    raw = form.get("refresh_token")
    try:
        record, revoked = ctx.store.get_refresh(raw)
    except KeyError:
        raise OAuthError(400, "invalid_grant", "Unknown refresh token")
    if revoked:
        raise OAuthError(400, "invalid_grant", "Refresh token revoked")
    if record.client_id != client.client_id:
        raise OAuthError(400, "invalid_grant", "Refresh token belongs to another client")
    if record.expires_at and record.expires_at < time.time():
        raise OAuthError(400, "invalid_grant", "Refresh token expired")

    ctx.store.revoke_refresh(raw)  # rotate
    audience = record.resource or ctx.resource_url
    access, claims = mint_jwt(
        ctx.private_key,
        issuer=ctx.issuer,
        audience=audience,
        subject=record.subject,
        client_id=client.client_id,
        scopes=record.scopes,
        ttl_seconds=ctx.token_ttl,
    )
    new_refresh = ctx.store.create_refresh(
        client_id=client.client_id,
        scopes=record.scopes,
        resource=audience,
        subject=record.subject,
        ttl_seconds=ctx.refresh_ttl,
    )
    return _token_response(access, claims["exp"], new_refresh, record.scopes)


def _token_response(access: str, expires: int, refresh: str, scopes: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": max(1, expires - int(time.time())),
            "refresh_token": refresh,
            "scope": " ".join(scopes),
        }
    )


def _validate_authorize(ctx: OAuthContext, params: dict[str, str], *, redirect_target: str | None):
    error_text = _authorize_request_error(params)
    if error_text:
        raise OAuthError(400, "invalid_request", error_text)
    client = ctx.store.get_client(params["client_id"])
    if not client:
        raise OAuthError(401, "unauthorized_client", "Unknown client_id")
    if params["redirect_uri"] not in client.redirect_uris:
        raise OAuthError(400, "invalid_request", "redirect_uri is not registered for this client")
    if redirect_target is None:
        # POST: re-validate state from the original authorize request
        code_challenge = params.get("code_challenge")
        if not code_challenge or params.get("code_challenge_method", "S256").upper() != "S256":
            raise OAuthError(400, "invalid_request", "code_challenge (S256) is required (PKCE)")
    return client


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


def build_auth_routes(ctx: OAuthContext) -> list[Route]:
    """Build the OAuth Routes; attach ctx via request.state through a dependency."""
    routers = [
        Route("/.well-known/oauth-authorization-server", metadata_authorization_server),
        Route("/.well-known/oauth-protected-resource", metadata_protected_resource),
        Route("/oauth/jwks.json", jwks),
        Route("/oauth/register", register, methods=["POST"]),
        Route("/oauth/authorize", authorize_get, methods=["GET"]),
        Route("/oauth/authorize", authorize_post, methods=["POST"]),
        Route("/oauth/token", token, methods=["POST"]),
        Route("/oauth/revoke", revoke, methods=["POST"]),
    ]

    wrapped = [_wrap_with_context(route, ctx) for route in routers]
    return wrapped


def _wrap_with_context(route: Route, ctx: OAuthContext) -> Route:
    """Wrap a handler so ``request.state.oauth`` is populated (plain Starlette apps have no
    middleware for state injection; we rely on the outer ASGI wrapper instead)."""

    async def handler(request: Request):
        request.state.oauth = ctx
        try:
            return await route.endpoint(request)
        except OAuthError as exc:
            return _json_error(exc)

    return Route(route.path, handler, methods=route.methods, name=route.name)