# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 - 2026-10-14

First release. A production-shaped, multi-tool MCP server platform that exposes
the whole suite through a single remote server.

### Added

- **Tool suite (10 tools):** `index_document`, `semantic_search`, `document_qa`,
  `analyze_document`, `review_code`, `analyze_data`, `web_research`,
  `generate_report`, `email_assistant` and `usage_stats`. Every tool is a plugin
  registered through a pluggable `ToolRegistry`.
- **Server core:** MCP over streamable HTTP (default) and stdio, with a provider
  abstraction for LLMs (groq / ollama / openai / anthropic / fake) and embeddings
  (ollama / openai / hashing).
- **Retrieval-augmented generation:** PDF / URL / raw-text ingestion, chunking,
  embedding and a `VectorStore` interface with in-memory and optional
  **pgvector** backends (`VECTOR_STORE=pgvector`).
- **Auth:** bearer API key and a full **OAuth 2.1** authorization server +
  resource server (RFC 8414 / 7591 / 7636 / 8707 / 9728, PKCE, JWT, refresh
  token rotation).
- **Usage / cost dashboard:** `usage_stats` tool and `GET /stats` reporting call
  counts, latency and estimated USD cost.
- **MCP Apps widget** (`io.modelcontextprotocol/ui`): an interactive HTML usage
  dashboard rendered in a sandboxed iframe, with a plain-text fallback for
  clients that don't support Apps.
- **MCP Tasks** (protocol `2025-11-25`): `web_research` and `generate_report`
  can run as background tasks via a task-augmented `tools/call`, with
  `tasks/get`, `tasks/list`, `tasks/cancel` and `tasks/result` support and an
  in-process `TaskStore`; `tasks/cancel` stops the in-flight run.
- **Evaluation harness:** per-tool offline evaluators, sample testset and
  `python -m evals` / `mcp-tool-suite-eval` entry points.
- **Packaging & ops:** multi-stage non-root Docker image with healthcheck,
  `docker compose` setup, `.env.example`, and a GitHub Actions CI workflow
  (pytest + offline eval).
- **Tests:** offline pytest suite (92 passing, 3 pgvector tests skipped without a
  database) and per-client connection guides.

