# Connecting real MCP clients

This server speaks **Streamable HTTP** at `http://<host>:<port>/mcp` (and stdio
when launched locally). Any MCP-capable client connects with **no client-specific
code**. This guide covers the popular clients across all three auth modes.

## 1. Start the server in the mode you want

Pick a server mode first; every client snippet below then just needs the right URL
and (optionally) a credential.

```powershell
# A) Local, no auth (easiest to try)
$env:AUTH_MODE="none"; $env:TRANSPORT="streamable-http"
$env:LLM_PROVIDER="fake"; $env:EMBED_PROVIDER="hashing"
python run.py

# B) Static API key
$env:AUTH_MODE="bearer"; $env:API_KEY="a-long-random-secret"
python run.py

# C) OAuth 2.1 (recommended for anything public)
$env:AUTH_MODE="oauth2"; $env:PUBLIC_BASE_URL="http://localhost:8000"
$env:OAUTH_DEMO_USER="admin"; $env:OAUTH_DEMO_PASSWORD="change-me"
python run.py
```

Confirm the server is up: `curl http://localhost:8000/health` returns the tool list.

**Choosing how to connect**

| Situation | Use |
|---|---|
| Same machine as the client | **stdio** (client launches the process) — simplest, no network auth |
| Remote/always-on server, trusted network | **streamable-http** + `bearer` |
| Remote/public, or any modern OAuth client | **streamable-http** + `oauth2` |
| Public SaaS UI (e.g. ChatGPT) | **streamable-http** + `oauth2` over **HTTPS** |

> **OAuth and HTTPS:** remote MCP clients only accept OAuth authorization servers
> over HTTPS, treating `localhost`/`127.0.0.1` as secure. Put the server behind TLS
> (reverse proxy, tunnel, or your host's TLS) before pointing a public client at it.

---

## stdio (local clients)

For clients that launch a local process, point them at `run.py` with `TRANSPORT=stdio`.
The server speaks JSON-RPC over stdio and needs no auth.

```json
{
  "mcpServers": {
    "mcp-tool-suite": {
      "command": "python",
      "args": ["C:\\Users\\you\\mcp-tool-suite\\run.py"],
      "env": { "TRANSPORT": "stdio", "LLM_PROVIDER": "groq", "GROQ_API_KEY": "..." }
    }
  }
}
```

On macOS/Linux swap the path (`/home/you/.../run.py`) and, if needed, `"command": ".venv/bin/python"`.

---

## Claude Desktop

Config file:
- Windows `%APPDATA%\Claude\claude_desktop_config.json`
- macOS `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux `~/.config/Claude/claude_desktop_config.json`

**stdio (local)**

```json
{
  "mcpServers": {
    "mcp-tool-suite": {
      "command": "python",
      "args": ["C:\\path\\to\\mcp-tool-suite\\run.py"],
      "env": { "LLM_PROVIDER": "fake", "EMBED_PROVIDER": "hashing" }
    }
  }
}
```

**Remote** — the reliable path today is the `mcp-remote` bridge, which speaks
OAuth/bearer on Claude's behalf:

```json
{
  "mcpServers": {
    "mcp-tool-suite": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://your-host/mcp"]
    }
  }
}
```

For `bearer` mode add the header:
`["-y", "mcp-remote", "https://your-host/mcp", "--header", "Authorization: Bearer YOUR_API_KEY"]`.

Newer Claude builds also support remote servers directly via **Settings →
Connectors → Add custom connector** (enter the `/mcp` URL; OAuth is detected
automatically via our `.well-known` metadata). Restart Claude after editing the file.

---

## Claude Code (CLI)

```powershell
# Remote, no auth
claude mcp add --transport http mcp-tool-suite http://localhost:8000/mcp

# Remote + bearer key
claude mcp add --transport http --header "Authorization: Bearer YOUR_API_KEY" `
  mcp-tool-suite https://your-host/mcp

# Local stdio
claude mcp add mcp-tool-suite -- python C:\path\to\mcp-tool-suite\run.py

claude mcp list
```

For `oauth2`, `--transport http` against an HTTPS URL triggers the browser
authorization flow automatically.

---

## VS Code (GitHub Copilot agent mode)

Create `.vscode/mcp.json` in your workspace (or run **MCP: Add Server** from the
Command Palette):

```json
{
  "servers": {
    "mcp-tool-suite": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

Omit `headers` for `none`; for `oauth2` use the HTTPS URL without headers and
VS Code runs the OAuth flow. Local stdio variant:

```json
{
  "servers": {
    "mcp-tool-suite": { "type": "stdio", "command": "python", "args": ["C:\\path\\to\\run.py"] }
  }
}
```

---

## Cursor

Create `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "mcp-tool-suite": {
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

`oauth2`: drop `headers`, use the HTTPS URL — Cursor performs dynamic client
registration and the browser consent flow. stdio uses `"command"`/`"args"` as above.

---

## ChatGPT

ChatGPT connectors take a URL only (no custom headers), so use `oauth2` (or `none`)
over a **public HTTPS** URL.

1. Make the server publicly reachable over HTTPS (e.g. a tunnel or a reverse proxy).
   Set `PUBLIC_BASE_URL=https://your-host` and `AUTH_MODE=oauth2`.
2. In ChatGPT: **Settings → Connectors → Advanced → Developer mode → Add custom
   connector**, enter `https://your-host/mcp`.
3. ChatGPT reads `/.well-known/oauth-protected-resource`, registers itself, and
   opens the consent screen — sign in with `OAUTH_DEMO_USER` / `OAUTH_DEMO_PASSWORD`.

Because bearer mode uses a header ChatGPT can't send, it won't work there.

---

## opencode

Add to `opencode.json` (project) or your global config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "mcp-tool-suite": {
      "type": "remote",
      "url": "http://localhost:8000/mcp",
      "enabled": true,
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

For `none`, omit `headers`. For `oauth2`, omit `headers` and use the HTTPS URL —
opencode handles discovery and consent. Local stdio:

```json
{
  "mcp": {
    "mcp-tool-suite": {
      "type": "local",
      "command": ["python", "C:\\path\\to\\mcp-tool-suite\\run.py"],
      "environment": { "LLM_PROVIDER": "fake", "EMBED_PROVIDER": "hashing" },
      "enabled": true
    }
  }
}
```

---

## Generic MCP clients & manual testing

- **MCP Inspector**: run `npx @modelcontextprotocol/inspector`, choose transport
  **Streamable HTTP**, URL `http://localhost:8000/mcp` (add an `Authorization`
  header if using `bearer`).
- **Raw bearer call**:

  ```powershell
  curl -X POST http://localhost:8000/mcp `
    -H "Authorization: Bearer YOUR_API_KEY" -H "Content-Type: application/json" `
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```

- **Full OAuth walkthrough in code**: `python examples/oauth_flow.py`
  (discovery → register → PKCE → token → authenticated tool call).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401` on `/mcp` | Send the `Authorization: Bearer …` header (bearer) or complete the OAuth flow. Check `WWW-Authenticate` for the `resource_metadata` URL. |
| Client reports "OAuth requires HTTPS" | OAuth only works over HTTPS (or `localhost`/`127.0.0.1`). Set a real `PUBLIC_BASE_URL` behind TLS. |
| Login page rejects credentials | They come from `OAUTH_DEMO_USER` / `OAUTH_DEMO_PASSWORD`; change them before exposing the server. |
| Tool list is empty / connection refused | Verify `curl /health`, that `TRANSPORT=streamable-http`, and the port matches. |
| ChatGPT connector fails | URL must be public HTTPS; use `oauth2` or `none` (no custom headers). |
| Remote server never authenticates | Confirm `PUBLIC_BASE_URL` matches the exact origin clients use — the JWT audience is bound to it (RFC 8707). |