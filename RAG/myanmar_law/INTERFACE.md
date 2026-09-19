# Myanmar Law Database Interface

## Public Python API

Import from `RAG.myanmar_law`:

```python
from RAG.myanmar_law import (
    ensure_myanmar_database_ready,
    exact_search,
    fuzzy_search,
    semantic_search,
    link_search,
    reset_engine,
)
```

`ensure_myanmar_database_ready(*, force_rebuild=False) -> dict` creates or reuses
`RAG/myanmar_law/cache/myanmar_law.db`. It returns `mode`, `content_sha256`,
`db_path`, `schema_version`, `document_count`, and `entry_count`.

`exact_search(title, article_number) -> str` returns a JSON string with
`success`, `message`, `data`, and `search_time`. An empty `article_number`
returns the first searchable entry for an exact title.

`fuzzy_search(query, limit=5) -> str` and its alias
`semantic_search(query, limit=5) -> str` return `success`, `message`, `data`,
`total_count`, `returned_count`, and `search_time`. The implementation is
Unicode substring search with deterministic ranking; it does not claim vector
semantic equivalence.

`link_search(message, limit=5) -> str` returns `success`, `message`, readable
`text`, `references`, complete `data`, and `search_time`. Every reference
contains `title`, `article_number`, `url`, and `content`.

`reset_engine() -> None` clears the process-local engine singleton.

## Hit object fields

Every hit includes the required `law_name`, `article_number`, `content`, and
`url` fields. It also includes the coordination fields `rule_id`, `source_id`,
`status`, `effective_date`, `language`, `country`, `country_label`,
`jurisdiction`, and `legal_system`.

Myanmar-specific provenance fields include `document_id`, `file_id`,
`source_document_url`, `source_sha256`, PDF page bounds, extraction and release
status, translation status, authority note, and a nested `provenance` object.

## Reliability contract

The corpus stores the source-language text and does not generate a translation.
The cited source document controls. OCR-derived and machine-split entries remain
`review_required` and `machine_extracted_unverified` or
`machine_split_unverified`; callers must not present those flags as official
legal verification.

This package does not register an LLM Tool and does not modify `tools`, `mcps.py`,
`function_calling.py`, or the PRC database.
