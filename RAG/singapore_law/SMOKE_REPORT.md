# Singapore Written Law Smoke Report

Date: 2026-09-19

Result: `ALL_PASS`

## Verified cases

1. Database readiness returned `full` on rebuild and produced 10 records.
2. Exact search resolved `Central Provident Fund (Amendment) Act 2026`, section 1, to `SG-EGAZETTE-2026-ACT14-SEC1`.
3. Chinese navigation query `中央公积金 投资` returned the correct Act while preserving English as the authoritative text.
4. The `semantic_search` compatibility alias returned results using the fuzzy retrieval implementation.
5. Natural-language link search resolved section 2 and returned both the main `data` records and compatible `references` fields.
6. The dedicated pytest module passed all 6 tests.

## Commands

```text
python -m RAG.singapore_law.scripts.assembly_smoke_cases
python -m pytest tests/test_singapore_law.py -q
```

## Recorded output

```json
{"status":"ALL_PASS","cases":[{"case":"ensure","mode":"full"},{"case":"exact","rule_id":"SG-EGAZETTE-2026-ACT14-SEC1"},{"case":"fuzzy_zh","returned":2},{"case":"semantic_alias","returned":3},{"case":"link","references":1}]}
```

Pytest result: `6 passed`.

The wider repository test suite was not an acceptance gate for this isolated package in the current environment because unrelated modules require project dependencies and credentials that are not installed or configured there, including FastAPI, OpenAI, dateparser, PyMuPDF, and DELI credentials.
