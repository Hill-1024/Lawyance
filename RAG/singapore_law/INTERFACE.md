# Singapore Written Law Interface

## Return convention

`exact_search`, `fuzzy_search`, `semantic_search`, and `link_search` return a JSON string encoded with `ensure_ascii=False`. Callers should decode it with `json.loads`.

`ensure_singapore_law_database_ready` returns a Python dictionary.

## Readiness function

```python
ensure_singapore_law_database_ready(*, force_rebuild: bool = False) -> dict
```

Returned keys:

- `rebuilt`: whether this call rebuilt the SQLite file
- `mode`: `full` or `unchanged`
- `content_sha256`: hash of the schema version and seed content
- `db_path`: independent Singapore database path
- `schema_version`: adapter schema version
- `record_count`: loaded section count

## Exact search

```python
exact_search(title: str, article_number: str) -> str
```

Envelope:

```json
{
  "success": true,
  "message": "exact match",
  "data": {},
  "search_time": 0.0
}
```

The title is matched case-insensitively after Unicode and punctuation normalization. `section 2`, `s. 2`, `article 2`, `2`, and `第2条` normalize to the same section identifier.

## Fuzzy and semantic search

```python
fuzzy_search(query: str, limit: int = 5) -> str
semantic_search(query: str, limit: int = 5) -> str
```

`limit` is clamped to 1 through 20. The current seed uses SQLite FTS5 when available and a normalized substring fallback. `semantic_search` is an API-compatible alias; vector embeddings are not claimed.

Envelope:

```json
{
  "success": true,
  "message": "matches found",
  "data": [],
  "total_count": 1,
  "returned_count": 1,
  "search_time": 0.0
}
```

## Link search

```python
link_search(message: str, limit: int = 5) -> str
```

The resolver recognises an Act title or Act citation together with English or Chinese section references. If no direct reference is found, it falls back to fuzzy search.

Envelope:

```json
{
  "success": true,
  "message": "references resolved",
  "text": "readable multi-line citations",
  "references": [
    {
      "title": "Act title",
      "article_number": "section 2",
      "url": "https://assets.egazette.gov.sg/...",
      "content": "authoritative English section text"
    }
  ],
  "data": [],
  "search_time": 0.0
}
```

## Record fields

Every record contains the four coordination fields:

- `law_name`
- `article_number`
- `content`
- `url`

It also contains:

- traceability: `rule_id`, `source_id`, `source_sha256`, `source_text_sha256`, `source_local_path`
- jurisdiction: `country`, `country_label`, `jurisdiction`, `legal_system`
- status: `status`, `status_note`, `effective_date`, `enactment_date`, `gazette_date`
- source classification: `document_type`, `authority_level`, `legal_hierarchy`, `promulgating_body`
- retrieval aids: `article_title`, `citation`, `subject_matter`, `topic_zh`
- common-law extension placeholders: `case_name`, `court`, `year`, `reporter`, `holding`, `ratio`, `obiter`, `precedential_status`

For legislation records, case-law fields are empty and `precedential_status` is `not_applicable`. This prevents legislation from being represented as a judgment.

## Status and translation safeguards

The seed uses `status: unknown` because eGazette publication alone does not prove the current consolidated status. The `status_note` tells consumers to check Singapore Statutes Online.

The authoritative language is `en`. `topic_zh` is for navigation only, and every record carries a `translation_notice` stating that it does not replace the authoritative English text.
