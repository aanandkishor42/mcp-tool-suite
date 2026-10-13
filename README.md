# MCP Tool Suite

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
  server.py        MCPServer + Starlette app assembly
  providers/       base · openai_compatible · anthropic · fake · hashing · router
  services/        documents (load/chunk/html) · vectorstore · rag
                   · code_analysis (AST) · data_analysis (CSV) · web (search)
  tools/           rag_tools · analyze · code_review · data_analysis · web_research · report
                   (+ add your own)
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
```

Tests run fully offline (fake LLM + hashing embeddings + in-memory vectors).


## Evaluation

Run offline evaluations of the RAG tools using the built-in harness:

`powershell
mcp-tool-suite-eval --samples evals/data/sample.json --output evals/results/latest.json
# or
python -m evals --samples evals/data/sample.json --output evals/results/latest.json
`

Results include keyword coverage, answered rate, and per-sample details. See evals/runner.py and evals/data/ for customization.



```powershell
docker compose up --build        # http://localhost:8000/mcp
```

---

## Roadmap

- [x] Tool suite: document/RAG + code review + data analysis + web research + report generator
- [x] OAuth 2.1 authorization + resource server (RFC 8414/7591/7636/8707/9728, PKCE, JWT, refresh rotation)
- [x] Postgres + pgvector backend behind the `VectorStore` interface (`VECTOR_STORE=pgvector`)
- [ ] Long-running work as MCP **Tasks** (e.g. expensive report generation)
- [ ] **MCP Apps** widgets for the usage/cost dashboard
- [ ] More tools: email assistant, dashboard
- [ ] Eval harness per tool (reusing the RAG-eval approach)

## License

MIT
