# Singapore Written Law Build and Handoff

## Delivery status

Version 1.0 is ready for database-protocol review. It provides an independent package, deterministic SQLite build, content fingerprint, exact and fuzzy retrieval, reference resolution, documentation, and an executable smoke suite. It deliberately does not register an LLM tool.

## Formal seed coverage

The seed contains sections 1 and 2 from each of five Acts published in the official 2026 eGazette:

1. Road Traffic Miscellaneous Amendments Act 2026
2. Central Provident Fund Amendment Act 2026
3. Securities and Futures Amendment Act 2026
4. Statutes Miscellaneous Amendments Act 2026
5. Energy Conservation Amendment Act 2026

This produces 10 section records covering transport, retirement savings, financial regulation, cross-department statutory amendments, and energy conservation.

Each source PDF was downloaded from `assets.egazette.gov.sg`, checked against the collection manifest SHA-256, parsed from the English PDF text layer, and exported with source and section-text hashes. The reproducible exporter is `SingaporeLaw/scripts/export_lawyance_seed.py` in the adjacent collection workspace.

## Database build

- database: `RAG/singapore_law/cache/singapore_law.db`
- manifest: `RAG/singapore_law/cache/manifest.json`
- schema version: `1.0.0`
- rebuild key: SHA-256 over schema version plus `data/official_seed.json`
- rebuild modes: `full`, `unchanged`
- FTS: SQLite FTS5 when available, normalized substring fallback otherwise

## Compliance and scope controls

- The stored text is official English Gazette text, not a third-party translation.
- Chinese terms are short project-authored topic labels and are explicitly non-authoritative.
- The seed does not claim that a provision is currently in force. Current status must be checked on Singapore Statutes Online.
- Bills, general Gazette notices, regulatory guidance, and case law are not mixed into this legislation seed.
- The project must retain the Singapore Government copyright and accuracy notice when this corpus is used beyond internal interface testing.

## Known limitations

- This is a 10-record integration seed, not the completed 28,451-document corpus index.
- Current consolidated status and commencement dates are not yet joined from Singapore Statutes Online because the compliant collection window returned HTTP 403.
- Case law is outside the present written-legislation scope; judgment citation parsing and binding or persuasive status require a separate corpus.
- `semantic_search` currently preserves the interface by delegating to fuzzy retrieval; embeddings are not included.
- The source exporter targets the current collection layout and requires `pypdf`.

## Handoff answers

1. Package protocol: yes, implemented as `RAG/singapore_law` with an independent cache.
2. First formal entries: 10 sections from 5 official 2026 Acts across transport, CPF, securities, miscellaneous amendments, and energy conservation.
3. Coordination support requested: confirm whether the assembly layer wants one Singapore written-law tool or a shared common-law router; separately agree the schema and citation parser for future judgments.

## Coordination requirement matrix

| Requirement | Implementation | Status |
|---|---|---|
| Independent jurisdiction package | `RAG/singapore_law` | Complete |
| Independent corpus and cache | `data/official_seed.json` and `cache/singapore_law.db` | Complete |
| Content fingerprint and conditional rebuild | schema plus data SHA-256 manifest | Complete |
| `ensure_*_database_ready` returns a dictionary | `ensure_singapore_law_database_ready` | Complete |
| `exact_search` JSON-string envelope | title plus normalised section lookup | Complete |
| `fuzzy_search` and `semantic_search` envelope | FTS5 with substring fallback and compatibility alias | Complete |
| `link_search` compatible references | `text`, `references`, and full `data` | Complete |
| Four required record fields | `law_name`, `article_number`, `content`, `url` | Complete |
| Recommended jurisdiction and status fields | traceability, dates, language, country, jurisdiction, legal system | Complete |
| Common-law extension fields | judgment fields present but explicitly inapplicable to legislation | Complete |
| Documentation set | `README.md`, `INTERFACE.md`, `BUILD.md` | Complete |
| Executable smoke suite | `scripts/assembly_smoke_cases.py` plus pytest module | Complete |
| No LLM tool self-registration | prohibited assembly files left unchanged | Complete |

## Acceptance commands

Run from the Lawyance repository root:

```text
python -m RAG.singapore_law.scripts.assembly_smoke_cases
python -m pytest tests/test_singapore_law.py
```

Acceptance requires an `ALL_PASS` smoke result and a zero pytest exit code.
