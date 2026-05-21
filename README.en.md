# Lawyance

[中文](./README.md) | English | [日本語](./README.ja.md)

Lawyance is a Chinese legal AI assistant project built by the GDUT legal intelligence team. It combines legal consultation, statute retrieval, case matching, company information lookup, contract/PDF/Word document handling, conversation-level memory, and a frontend workspace into one application. The goal is not to return unverifiable one-line answers, but to structure legal questions into facts, authorities, retrieved evidence, and analysis paths that can be checked further.

The repository contains a FastAPI backend, a React/Vite frontend, a tool forwarding layer, legal data clients, document processors, a conversation memory system, and an output review flow. Module boundaries matter: business tools are exposed to agents through `mcps`, and product code should not bypass that middleware.

## Product Positioning

- A Chinese legal AI assistant prototype.
- Supports direct answer and Plan-and-Solve modes for different levels of task complexity.
- Connects agents to statutes, cases, company data, and document processors through tools.
- Keeps stable facts, user constraints, and working boundaries through conversation-level memory.
- Uses a frontend workspace to manage uploaded files, generated files, and conversation context.

## Capabilities

- **Legal and web retrieval**: exact statute lookup, natural-language statute search, source link confirmation, similar-case matching, and public web search through self-hosted SearXNG.
- **Company information**: company profile, listing information, contacts, shareholders, registration data, key personnel, and external investments.
- **Document processing**: PDF text extraction, sentence-level PDF annotation, Word reading, and Word annotation writing.
- **Agent modes**: default answer and Plan-and-Solve workflows.
- **Conversation workspace**: isolates `TEMP` and `Result` file spaces by user and conversation.
- **Conversation memory**: records and retrieves stable facts, goals, constraints, and semantic tags without stuffing all history into the prompt.
- **Auth and audit**: login, roles, admin account management, API access logs, and basic rate limiting.
- **Frontend experience**: React 19 + Vite UI with chat, files, workspace, theme settings, admin dashboard, and Lawyance branding.

## Architecture

```text
React / Vite frontend
    |
    | REST / stream / file workspace
    v
FastAPI application
    |
    | agent orchestration
    v
Default / Plan-and-Solve agents
    |
    | tool descriptions + calls
    v
mcps tool forwarding layer
    |
    | legal data / company data / document processors / memory client
    v
MCP clients and local services
```

Important paths:

| Path | Purpose |
| --- | --- |
| `agent.py` | FastAPI app, auth dependencies, rate limiting, logs, file workspace, and main APIs |
| `function_calling.py` | Model calls, tool orchestration, and multi-system prompt forwarding |
| `agents/` | Unified native tool loop and Plan-and-Solve orchestration |
| `mcps.py` | Unified business tool forwarding layer |
| `mcp/` | Legal, company, PDF, Word, memory, and SearXNG web-search tool clients |
| `memory_system/` | Conversation-level structured memory service |
| `RAG/` | Local legal data retrieval logic |
| `src/` | React frontend application |
| `tests/` | Tests for memory and output review behavior |

## Requirements

- Python 3.13 or newer.
- Node.js and pnpm.
- Access to the required model service and business data sources.
- A local `.env` file in the repository root for model API keys and local configuration.

Do not commit API keys, account credentials, or real client materials. Use `.env_example` as a starting point:

```env
API_KEY="your_api_key_here"
```

## Installation

```bash
pnpm install
pip install -r requirements.txt
```

The repository also includes `pyproject.toml` and `uv.lock`. If your local workflow uses uv, install Python dependencies according to the team's convention.

## Development

Build the frontend assets:

```bash
pnpm run build
```

Start the full application:

```bash
pnpm run dev
```

This runs `python agent.py`. To start only the Vite frontend development server:

```bash
pnpm run dev:frontend
```

Common scripts:

| Command | Description |
| --- | --- |
| `pnpm run dev` | Start the FastAPI application |
| `pnpm run dev:frontend` | Start the frontend development server |
| `pnpm run build` | Build the frontend |
| `pnpm run preview` | Preview the frontend build |
| `pnpm run lint` | Run TypeScript checks |
| `pnpm run clean` | Remove frontend build output |

## Tests

```bash
python -m pytest
```

Current tests focus on:

- `tests/test_memory_system.py`: conversation memory recording, retrieval, constraint handling, and context generation.
- `tests/test_ocp.py`: output review fallbacks, completion state, and exceptional paths.

## Backend Topology and Tool Registry

`agent.py` only preserves the `agent:app` import contract and `python agent.py` entrypoint. Application assembly lives in `app_factory.py`; HTTP routes live in `routes/`; chat pipeline, history compression, memory coordination, and cleanup jobs live in `services/`.

Route registration order must remain: auth, admin, chat, workspace/upload/download, then SPA catch-all. `routes/spa.py` must be registered last so `/api/*` is never swallowed by the frontend fallback.

Business tools still reach agents through `mcps.py`. To add a tool:

1. Implement the real client or handler under `mcp/`.
2. Register its schema, handler, coercer, and `exposure` explicitly in `tools/__init__.py`.
3. Call it through `mcps.use_tools()`; agents, routes, and services should not bypass `mcps`.

`exposure` is the single source of truth for tool visibility:

- `agent`: visible in the main LLM tool schema.
- `plan_and_solve`: visible in Plan-and-Solve mode, including business tools and control-plane tools.
- `ocp_reviewer`: read-only legal source tools available to OCP.
- `internal`: backend-dispatchable tools that are hidden from the LLM tool schema.

Workspace path validation lives in `workspace.py`, shared by `mcps.py` and `tools/*`, so registry modules never need to import back from `mcps`.

OCP is a post-answer formatting review pass. Main-model failures still follow the main-model error path; OCP timeout, network failure, tool failure, or reviewer failure must not raise into the user path. It falls back to deterministic sanitizer-only output while preserving the main-model answer.

This architecture work does not include Lawyance naming cleanup, tool naming rewrites, or agent reasoning strategy rewrites.

The web-search tool uses self-hosted SearXNG and does not depend on third-party search APIs such as Tavily or SerpAPI. `web_search` only returns structured results and snippets; when full page text is needed, the model should call `web_fetch`. `web_fetch` marks returned page text as untrusted web data and it must not be followed as instructions.

Optional environment variables:

- `SEARXNG_BASE_URL`: SearXNG instance URL, default `https://serp.mutsumi.moe/`
- `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`: Cloudflare Access Service Auth headers; the older `SEARXNG_CF_ACCESS_CLIENT_ID` / `SEARXNG_CF_ACCESS_CLIENT_SECRET` names remain supported
- `SEARXNG_ENGINES`, `SEARXNG_CATEGORIES`, `SEARXNG_LANGUAGE`, `SEARXNG_SAFE_SEARCH`: default search parameter overrides; normally let server-side `settings.yml` and `categories` route engines, and set `SEARXNG_ENGINES` only when exact engines must be pinned
- `SEARXNG_TIMEOUT`, `SEARXNG_MAX_RESULTS`, `SEARXNG_MAX_RESPONSE_BYTES`: request and result size limits; defaults are 20 seconds and 10 results

## Conversation Memory and RAG Weights

The memory system remains conversation-level structured memory. Retrieval fuses multiple signals: lexical matches, semantic tags, entities, recency, priority, and active focus. When optional embedding retrieval is enabled, vector similarity is added as one `embedding` signal in the same RAG-weighted ranker instead of replacing the existing multi-route retrieval.

Optional environment variables:

- `MEMORY_EMBEDDING_ENABLED=1`: enable embedding as a retrieval weight, disabled by default
- `EMBEDDING_API_KEY`: API key for the embedding service
- `EMBEDDING_BASE_URL`: OpenAI-compatible embedding base URL, default `https://api.siliconflow.cn/v1`
- `EMBEDDING_MODEL`: embedding model, default `Qwen/Qwen3-Embedding-8B`
- `MEMORY_EMBEDDING_TIMEOUT`: embedding request timeout, default 8 seconds

## Development Boundaries

- `mcps.py` is the unified business-facing tool entry point for agents. New tools should be implemented in `mcp/` clients and exposed through `mcps`, instead of being called directly by agents or API routes.
- The memory system is conversation-level structured memory. It is not user-level profiling; optional embedding is only a retrieval weight signal.
- Uploaded and generated files must stay inside the user/conversation workspace boundary.
- Legal answers should preserve a verifiable chain: facts, statutes, cases, or source links should remain traceable.
- Frontend migration and UI work should follow the Lawyance design system, not hide layout issues with padding hacks or compatibility layers.

## Security Notes

- `.env`, real contracts, client materials, generated results, and logs may contain sensitive information and should not be committed casually.
- First deployment must set `SECRET_KEY` with at least 32 random characters and a one-time `INITIAL_ADMIN_PASSWORD`; remove the initial password variable after `data/account.json` is created.
- Current CORS, rate limit, and auth defaults fit an internal prototype. Public deployment requires domain-specific hardening.
- Admin APIs can manage accounts and read logs, so they should only be available to trusted administrators.
- File annotation, document reading, and download APIs require ongoing attention to path isolation and permissions.

## License

The project source code is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](./LICENSE).

Reuse, modification, redistribution, or offering this project as a network service must comply with AGPL-3.0. Business data, third-party data sources, model services, and real client materials are not automatically licensed by this repository; confirm team authorization and data compliance requirements before use.
