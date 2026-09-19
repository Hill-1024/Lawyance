# Myanmar Law Database Build Record

## Scope

- Country: Myanmar
- Legal system routing value: `civil`
- Primary source: Myanmar Ministry of Information law portal
- Text policy: source-language text only; no machine translation is promoted as
  authoritative text
- Database isolation: `RAG/myanmar_law/cache/myanmar_law.db`
- Schema version: 1

## Pipeline

1. Collect MOI metadata and attachment relationships.
2. Download source attachments and retain SHA-256 provenance.
3. Extract usable embedded text and OCR only the pages that require OCR.
4. Merge pages in original PDF order.
5. Preserve machine provision splits as review-required candidates.
6. Build `data/documents.jsonl` with source and quality fields.
7. Build the independent SQLite cache from the JSONL fingerprint.
8. Run `scripts/assembly_smoke_cases.py` before handoff.

## Release rules

- The original-language source controls.
- OCR confidence is an engine signal, not legal or linguistic verification.
- Machine provision boundaries remain candidates until reviewed.
- Records with unknown effectiveness remain `status=unknown`.
- Every search hit retains a source page URL and source attachment provenance.
- Unreadable attachments stay outside searchable entries and remain in the OCR
  pipeline review queue.

## Coordination status

The Python API, envelope, independent cache, fingerprint rebuild, documentation,
and smoke test are implemented. LLM Tool registration is intentionally excluded.
The generated corpus report records the final counts and skipped reasons for the
specific OCR run used to build the database.

The 2026-09-19 build contains 685 searchable source documents and 13,122 search
entries: 12,792 machine-split provision candidates plus 330 whole-document
fallback entries. Attachment text classification found 618 Myanmar documents,
59 English documents, and 8 mixed Myanmar-English documents. Four unreadable
files were excluded, and 58 unsuccessful attachment relations were reported.

The table-structure screening also completed all 452 routed pages with zero
failures. It processed 525 table regions, emitted 68 review-only structure
candidates, and safely abstained on 457 regions. These candidates do not replace
or reorder the searchable source text automatically.
