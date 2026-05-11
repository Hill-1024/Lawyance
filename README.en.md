# GDUT-Lawyer

[中文](./README.md) | English | [日本語](./README.ja.md)

GDUT-Lawyer is a Chinese legal AI assistant project built by the GDUT legal intelligence team. It combines legal consultation, statute retrieval, case matching, company information lookup, contract/PDF/Word document handling, conversation-level memory, and a frontend workspace into one application. The goal is not to return unverifiable one-line answers, but to structure legal questions into facts, authorities, retrieved evidence, and analysis paths that can be checked further.

The repository contains a FastAPI backend, a React/Vite frontend, a tool forwarding layer, legal data clients, document processors, a conversation memory system, and an output review flow. Module boundaries matter: business tools are exposed to agents through `mcps`, and product code should not bypass that middleware.

## Product Positioning

- A Chinese legal AI assistant prototype.
- Supports direct answer, ReAct, and Plan-and-Solve modes for different levels of task complexity.
- Connects agents to statutes, cases, company data, and document processors through tools.
- Keeps stable facts, user constraints, and working boundaries through conversation-level memory.
- Uses a frontend workspace to manage uploaded files, generated files, and conversation context.

## Capabilities

- **Legal retrieval**: exact statute lookup, natural-language statute search, source link confirmation, and similar-case matching.
- **Company information**: company profile, listing information, contacts, shareholders, registration data, key personnel, and external investments.
- **Document processing**: PDF text extraction, sentence-level PDF annotation, Word reading, and Word annotation writing.
- **Agent modes**: default answer, ReAct tool use, and Plan-and-Solve workflows.
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
Default / ReAct / Plan-and-Solve agents
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
| `function_calling.py` | Model calls, tool orchestration, and system memory entry points |
| `agents/` | Default, ReAct, and Plan-and-Solve agent implementations |
| `mcps.py` | Unified business tool forwarding layer |
| `mcp/` | Legal, company, PDF, Word, and memory tool clients |
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

This repository does not declare an open-source license yet. Confirm team authorization and data compliance requirements before reuse, redistribution, or external deployment.
