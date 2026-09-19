# Myanmar Law Database

This package provides an independent, provenance-preserving search database for
Myanmar legal documents collected from the Myanmar Ministry of Information law
portal. It follows the Lawyance jurisdiction database interface while keeping
the Myanmar corpus separate from `RAG/cache/law.db`.

## Build the canonical corpus

From the repository root, run:

```powershell
python -m RAG.myanmar_law.build_corpus `
  --metadata "<MOI metadata>/legal_metadata.json" `
  --relations "<MOI downloads>/document_file_relations.json" `
  --merged-root "<formal OCR output>" `
  --provision-root "<formal OCR output>"
```

The command writes `data/documents.jsonl` and `data/documents.report.json`.
Each record retains the source page, source attachment URL, SHA-256, OCR/text
layer counts, verification status, and any machine-generated provision
candidates.

## Build or reuse the SQLite database

```powershell
python -c "from RAG.myanmar_law import ensure_myanmar_database_ready; print(ensure_myanmar_database_ready())"
```

The cache rebuilds only when the schema version or JSONL content fingerprint
changes.

## Run the smoke checks

```powershell
python -m RAG.myanmar_law.scripts.assembly_smoke_cases
```

Exit code zero and `ALL_PASS` mean the package is ready for coordination review.
Tool-layer registration remains a separate assembly task.

## Search notes

The fuzzy search works on the original Myanmar or English text. Chinese queries
only match when Chinese metadata or a separately authorized Chinese guide is
present. The package does not translate source text because translation rights
and review policy must be decided outside the retrieval layer.
