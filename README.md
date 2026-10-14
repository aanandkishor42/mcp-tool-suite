# MCP Tool Suite

[![CI](https://github.com/aanandkishor42/mcp-tool-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/aanandkishor42/mcp-tool-suite/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/aanandkishor42/mcp-tool-suite)](https://github.com/aanandkishor42/mcp-tool-suite/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A **multi-tool MCP server platform**: one remote server that exposes many
AI-callable tools over the [Model Context Protocol](https://modelcontextprotocol.io).
Connect it once to **Claude, ChatGPT, VS Code, Cursor or opencode** and every
client instantly gains the whole suite — you build the tools once.

> Built as a portfolio-grade, production-shaped project: pluggable tool registry,
> provider abstraction, retrieval-augmented generation, streaming HTTP transport,
> OAuth 2.1 auth, persistence, Docker and tests.

---

## Why this exists

MCP has become the industry standard for connecting AI agents to tools and data.
A single MCP server reaches every major client with **no client-specific code**.
This project demonstrates the whole stack behind that: protocol design, API and
schema design, authentication, databases/vector storage, AI integration, file
handling, semantic search and a clean developer experience.

## Tools

| Tool | What it does |
|---|---|
| `index_document` | Load a PDF / URL / raw text, chunk + embed it into a named collection |
| `semantic_search` | Return the most relevant chunks for a query, with scores and sources |
| `document_qa` | Answer a question grounded in indexed docs, with numbered citations |
| `analyze_document` | Summarize a document and extract key points and entities |
| `review_code` | Review code: static AST analysis for Python (functions, classes, imports, risky patterns) + LLM review |
| `analyze_data` | Profile a CSV/TSV (per-column numeric/categorical stats) + AI insights, optional question |
| `web_research` | Search the web (DuckDuckGo, no API key), fetch pages, synthesize a cited summary |
| `generate_report` | Write a structured Markdown report grounded in a collection and/or provided sources |
| `email_assistant` | Draft email, summarize a mailbox, or extract action items/open questions from `.eml`/mbox text |
| `usage_stats` | Report session tool/LLM call counts, latency and estimated USD cost (also at `GET /stats`) |

Every tool is a plugin — see **Adding a tool**.

---

## Quickstart (local, no API key)

Works offline using the deterministic `fake` LLM and `hashing` embeddings.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run as a remote MCP server
$env:TRANSPORT="streamable-http"; $env:LLM_PROVIDER="fake"; $env:EMBED_PROVIDER="hashing"
python run.py
```

Then connect a client (see below) or smoke-test the protocol:

```powershell
# Health + tool inventory
curl http://localhost:8000/health

# Usage/cost snapshot (tool + LLM call counts, latency, estimated cost)
curl http://localhost:8000/stats
```

### Use a real model

```powershell
copy .env.example .env      # then fill in keys
# Groq (free tier):  LLM_PROVIDER=groq, GROQ_API_KEY=...
# Ollama (local):    LLM_PROVIDER=ollama, EMBED_PROVIDER=ollama
# OpenAI / Claude:   LLM_PROVIDER=openai | anthropic
python run.py
```

| Provider | Free? | Notes |
|---|---|---|
| `groq` | yes | fast hosted LLMs, free tier |
| `ollama` | yes | fully local, no key (chat + `nomic-embed-text`) |
| `openai` | paid | best quality |
| `anthropic` | paid | Claude Messages API |
| `hashing` (embeddings) | yes | offline, deterministic — good for demos/tests |

### Vector store

Retrieval uses an in-process store by default. For production, switch to Postgres +
**pgvector** (`VECTOR_STORE=pgvector`) behind the same `VectorStore` interface:

```powershell
pip install "mcp-tool-suite[pgvector]"
# a Postgres with the vector extension, e.g.:
# docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=mcp pgvector/pgvector:pg17
$env:VECTOR_STORE="pgvector"; $env:PGVECTOR_DSN="postgresql://postgres:mcp@localhost:5432/postgres"
python run.py
```

| `VECTOR_STORE` | Backing | Notes |
|---|---|---|
| `memory` (default) | numpy + optional disk persistence | zero dependencies, offline |
| `pgvector` | Postgres + `pgvector` | shared, durable, scales; needs `PGVECTOR_DSN` |

The embedding dimension is taken from the active embedder, so switch
`EMBED_PROVIDER`/`EMBED_MODEL` together with the target database.

---

## Connect clients

One server, every client — no client-specific code. Add the `/mcp` URL to your
client's MCP config; full per-client, per-auth-mode instructions are in
**[`docs/connecting-clients.md`](docs/connecting-clients.md)**.

```json
{ "mcpServers": { "mcp-tool-suite": { "url": "http://localhost:8000/mcp" } } }
```

| Client | Config | Remote auth |
|---|---|---|
| Claude Desktop | `claude_desktop_config.json` | `mcp-remote` proxy / Connectors UI (OAuth) |
| Claude Code | `claude mcp add --transport http …` | header or OAuth |
| VS Code (Copilot) | `.vscode/mcp.json` | header or OAuth |
| Cursor | `.cursor/mcp.json` | header or OAuth |
| ChatGPT | Connectors → Developer mode | **OAuth only** (HTTPS, no headers) |
| opencode | `opencode.json` → `mcp` | header or OAuth |

Ready-made configs: `examples/client-config.json` (no auth),
`examples/client-config-auth.json` (bearer), `examples/client-config-oauth.json`.

Then just talk: *"Index this PDF and tell me what it says about pricing."*

---

## Transports

| Transport | Use |
|---|---|
| `streamable-http` (default) | remote / production; single `/mcp` endpoint; stateless core |
| `stdio` | local, launched as a subprocess by the client |

Set `TRANSPORT=stdio` and point the client at `python run.py`.

## Auth

Auth is selected with `AUTH_MODE`; `/health` always stays public.

| `AUTH_MODE` | What it does |
|---|---|
| `none` (default) | public endpoint — best for local dev |
| `bearer` | static API key; every `/mcp` request sends `Authorization: Bearer <API_KEY>` |
| `oauth2` | full **OAuth 2.1** authorization + resource server |

Both guards are pure-ASGI so streamed (SSE) responses are never buffered.

### OAuth 2.1 (`AUTH_MODE=oauth2`)

This server is both the authorization server and the resource server on one
origin, so any MCP client can self-configure from discovery alone:

- **Discovery** — `/.well-known/oauth-protected-resource` (RFC 9728) advertises the
  protected resource and its authorization server. A `401` includes
  `WWW-Authenticate: Bearer ... resource_metadata="<issuer>/.well-known/oauth-protected-resource"`.
- **Dynamic client registration** — `POST /oauth/register` (RFC 7591).
- **Authorization Code + PKCE** — `GET/POST /oauth/authorize` (S256 enforced, RFC 7636),
  with a minimal login/consent page seeded from `OAUTH_DEMO_USER` / `OAUTH_DEMO_PASSWORD`.
- **Tokens** — `POST /oauth/token` issues an **RS256 JWT** whose `aud` is this MCP
  resource URL (RFC 8707 audience binding, so tokens minted for any other service are
  rejected), plus rotating opaque refresh tokens (RFC 7009 revocation at `/oauth/revoke`).
- **Keys** — an RSA keypair is generated once and persisted under `DATA_DIR`, published
  at `/oauth/jwks.json`.

Enable it and connect:

```powershell
$env:AUTH_MODE="oauth2"; $env:PUBLIC_BASE_URL="http://localhost:8000"
python run.py
```

```powershell
python examples/oauth_flow.py   # registers a client and runs the whole flow end-to-end
```

---

## Architecture

```
Client (Claude / ChatGPT / VS Code / opencode)
        │  JSON-RPC over Streamable HTTP
        ▼
MCPServer  ── /mcp ──►  ToolRegistry (plugins)
   │                        │
   │                        ▼
   │                   tools/*  (typed, schema-validated)
   │                        │
   │                        ▼
   │                   services/  rag · vectorstore · documents
   │                        │
   ▼                        ▼
auth/ (bearer · oauth2)  providers/  LLM + embeddings (Groq/Ollama/OpenAI/Claude)
```

```
src/mcp_tool_suite/
  config.py        settings (pydantic-settings)
  auth/            bearer.py · tokens.py · store.py · routes.py · middleware.py
  context.py       dependency-injected AppContext
  registry.py      ToolRegistry + ToolPlugin protocol
  server.py        MCPServer + Starlette app assembly (incl. MCP Apps extension)
  providers/       base · openai_compatible · anthropic · fake · hashing · router
  services/        documents (load/chunk/html) · vectorstore · rag
                   · code_analysis (AST) · data_analysis (CSV) · email_analysis (MIME) · web (search)
                   · usage (UsageTracker + TrackedLLMProvider)
  tools/           rag_tools · analyze · code_review · data_analysis · web_research · report · email
                   · dashboard (usage_stats) (+ add your own)
docs/              connecting-clients.md (per-client setup)
examples/          client-config*.json · oauth_flow.py
```

## Adding a tool (plugin)

```python
# src/mcp_tool_suite/tools/word_count.py
from mcp_tool_suite.context import AppContext
from mcp_tool_suite.registry import ToolCallable


class WordCountTool:
    name = "word_count"
    description = "Count the words in a piece of text."

    def create(self, ctx: AppContext) -> ToolCallable:
        async def word_count(text: str) -> dict:
            return {"words": len(text.split())}
        return word_count
```

Register it in `tools/__init__.py::default_plugins` — that's it.

---

## Tests

```powershell
pip install -e ".[dev]"
pytest -q
ruff check .
```

Tests run fully offline (fake LLM + hashing embeddings + in-memory vectors).
Lint runs with [Ruff](https://docs.astral.sh/ruff/) (`E`, `F`, `I`, `UP`, `B` at a
120-column width) and is enforced by a dedicated CI job.


## Evaluation

Run the offline, **per-tool** evaluation harness (fake LLM + hashing embeddings +
no web search, so it needs no keys or network). Every tool is exercised with its
own metrics — keyword coverage, answered rate and citation count for the RAG
tools, static-analysis rule/severity matching for `review_code`, row/column shape
checks for `analyze_data`, source counts for `web_research`/`generate_report`,
action-item extraction for `email_assistant`, and usage totals for `usage_stats`:

```powershell
mcp-tool-suite-eval --samples evals/data/sample.json --output evals/results/latest.json
# or
python -m evals --samples evals/data/sample.json --output evals/results/latest.json
```

Each sample in `evals/data/sample.json` declares its target `tool` (default
`document_qa`) plus tool-specific `input` and `metadata` expectations. Results
contain per-sample outputs and an `aggregate` block grouped `by_tool`. Add new
evaluators in `evals/evaluators.py` and samples to the JSON to extend coverage.

## Usage & cost

Usage is tracked in-process for the lifetime of the server: every tool call
(latency, success/error) and every LLM call (provider/model, estimated tokens,
estimated USD cost). Read it two ways:

* **MCP tool** `usage_stats` — callable by any client; returns structured totals
  plus a Markdown dashboard.
* **HTTP** `GET /stats` — the same summary as JSON.

Token counts are estimated from character counts (`chars / 4`); cost comes from a
small per-provider price table (local `ollama`/`fake` are free). Override prices
for the active provider with `LLM_INPUT_PRICE_PER_1K` / `LLM_OUTPUT_PRICE_PER_1K`
(USD per 1,000 tokens).

### MCP Apps widget

`usage_stats` is also an **MCP App** (`io.modelcontextprotocol/ui`): its
`_meta.ui.resourceUri` points at the `ui://mcp-tool-suite/usage.html` resource, an
interactive HTML dashboard the host renders in a sandboxed iframe. Hosts that
support Apps render the widget; text-only clients get the plain text/Markdown
answer, so the tool degrades gracefully (SEP-2133). Nothing else is required to
enable it — the `Apps` extension is registered in `server.py:build_apps`.

### MCP Tasks (long-running tools)

Tools whose work is slow — `web_research` and `generate_report` — can be deferred
to a background **MCP Task** (protocol **2025-11-25**). Their `tools/list` entries
carry `execution.taskSupport: "optional"`, and the server advertises the `tasks`
capability with the `tools.call` request.

When a client sends `tools/call` with a `task` field (`{"ttl": <ms>}`), the server
returns a `CreateTaskResult` immediately and runs the tool in the background on the
event loop. The client then drives the lifecycle with the standard task methods:

| Method | Purpose |
| --- | --- |
| `tasks/get` | poll status (`working` → `completed`/`failed`/`cancelled`) |
| `tasks/list` | enumerate live tasks |
| `tasks/result` | fetch the final `CallToolResult` (errors until terminal) |
| `tasks/cancel` | cancel the background run (idempotent; terminal states are sticky) |

Tasks are held in an in-process `TaskStore` (`services/tasks.py`) and expire
`tasks_default_ttl_ms` after they finish. Passing `task` to a non-task tool is
rejected with `INVALID_PARAMS`. A missing `task` field runs the tool inline as
usual, so nothing changes for plain clients.

Tune via `TASKS_ENABLED`, `TASKS_DEFAULT_TTL_MS` and `TASKS_POLL_INTERVAL_MS`
(see `.env.example`). Tasks require the `2025-11-25` wire; on the newer
`2026-07-28` wire the `tasks/*` methods are absent and callers should fall back to
a synchronous call. Note: the bundled SDK client cannot parse a task-augmented
`tools/call` response, so exercise it with a wire-level client or the tests in
`tests/test_tasks.py`.


```powershell
docker compose up --build        # http://localhost:8000/mcp
```

---

## Releasing

Versioning follows [SemVer](https://semver.org), with releases driven by git tags
(`vX.Y.Z`) and `.github/workflows/release.yml`:

1. Bump `version` in `pyproject.toml` and add a dated entry to `CHANGELOG.md`.
2. Commit, then tag and push: `git tag -a vX.Y.Z -m "..." && git push origin main vX.Y.Z`.
3. Publish a GitHub Release for the tag — this triggers the workflow to build the
   sdist/wheel, attach them to the release, and publish to PyPI.

Publishing uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC — no API tokens). One-time setup on PyPI: add a **pending trusted publisher**
for project `mcp-tool-suite` with owner `aanandkishor42`, repository
`mcp-tool-suite`, workflow `release.yml`, and environment `pypi`. Until that is
configured the `publish-pypi` job will fail (the build and attach jobs still
succeed). You can also run the workflow manually via **Actions → Release → Run
workflow** and pass an existing tag.

## Roadmap

- [x] Tool suite: document/RAG + code review + data analysis + web research + report generator
- [x] OAuth 2.1 authorization + resource server (RFC 8414/7591/7636/8707/9728, PKCE, JWT, refresh rotation)
- [x] Postgres + pgvector backend behind the `VectorStore` interface (`VECTOR_STORE=pgvector`)
- [x] Long-running work as MCP **Tasks** (e.g. expensive report generation)
- [x] Usage/cost dashboard tool + stats endpoint
- [x] **MCP Apps** widget for the usage/cost dashboard (`io.modelcontextprotocol/ui`)
- [x] Eval harness per tool (reusing the RAG-eval approach)
- [x] Email assistant tool (draft · summarize · extract action items)

## License

MIT
