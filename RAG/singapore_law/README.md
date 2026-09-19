# Singapore Written Law Retrieval Package

This package is the common-law jurisdiction adapter for Singapore written legislation. It implements the database-level Python API required by the Lawyance coordination protocol and keeps its data and SQLite cache separate from `RAG/cache/law.db`.

## Current scope

- Jurisdiction: Singapore
- Legal system route: `common`
- Corpus type: written legislation only
- Seed: 10 complete sections from 5 Acts published in the 2026 Singapore Government Gazette
- Authority language: English
- Source: official eGazette PDF files with SHA-256 provenance

The seed is an interface and regression sample. It is not a complete current-law service and does not contain case law. Gazette publication proves the text as published; it does not by itself prove the current consolidated status or commencement of every provision. Check Singapore Statutes Online before relying on a result as current law.

Chinese topic terms are navigation aids only. They must not be quoted as an authoritative translation or used instead of the English text.

## Public API

```python
from RAG.singapore_law import (
    ensure_singapore_law_database_ready,
    exact_search,
    fuzzy_search,
    semantic_search,
    link_search,
    reset_engine,
)
```

- `ensure_singapore_law_database_ready(*, force_rebuild=False) -> dict`
- `exact_search(title, article_number) -> str`
- `fuzzy_search(query, limit=5) -> str`
- `semantic_search(query, limit=5) -> str`
- `link_search(message, limit=5) -> str`
- `reset_engine() -> None`

All search functions return JSON strings. `semantic_search` is currently an alias of keyword-based `fuzzy_search`; it does not claim vector-semantic behavior.

## Build and test

Run from the repository root:

```text
python -m RAG.singapore_law.scripts.assembly_smoke_cases
python -m pytest tests/test_singapore_law.py
```

The database is created at `RAG/singapore_law/cache/singapore_law.db`. A content hash over the schema version and seed data controls rebuilding. Set `SINGAPORE_LAW_DATA_PATH` or `SINGAPORE_LAW_CACHE_DIR` before import to use another data file or cache directory.

## Integration boundary

This package does not modify or register anything in `tools/__init__.py`, `mcps.py`, `function_calling.py`, or `mcp/pkulaw_client.py`. LLM tool registration remains a separate assembly task.

See `INTERFACE.md` for the envelope and field contract, `BUILD.md` for provenance and handoff status, and `SMOKE_REPORT.md` for the recorded acceptance result.
