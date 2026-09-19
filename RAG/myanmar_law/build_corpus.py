"""Build canonical Myanmar corpus JSONL from the MOI OCR pipeline outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean_status(value: Any) -> str:
    candidate = str(value or "unknown").casefold()
    return candidate if candidate in {"in_force", "repealed", "amended", "unknown"} else "unknown"


def detect_text_language(text: str) -> str:
    """Classify the extracted attachment text without translating it."""
    myanmar = sum(
        1
        for character in text
        if "\u1000" <= character <= "\u109f"
        or "\uaa60" <= character <= "\uaa7f"
        or "\ua9e0" <= character <= "\ua9ff"
    )
    latin = sum(1 for character in text if character.isascii() and character.isalpha())
    if myanmar >= 50 and myanmar >= latin * 0.15:
        return "my"
    if latin >= 50 and myanmar < latin * 0.02:
        return "en"
    return "my+en"


def build_corpus(
    *, metadata_path: Path, relations_path: Path, merged_root: Path,
    provision_root: Path, output_path: Path,
) -> dict[str, Any]:
    metadata = {item["document_id"]: item for item in load_json(metadata_path)}
    relations = load_json(relations_path)
    merged_manifest = load_json(merged_root / "merged_manifest.json").get("documents", [])
    merged_by_file = {item["file_id"]: item for item in merged_manifest if item.get("status") == "complete"}
    provision_manifest = load_json(provision_root / "provision_candidate_manifest.json").get("documents", [])
    provision_by_file = {item["file_id"]: item for item in provision_manifest}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    provision_count = 0
    skipped = Counter()
    languages = Counter()
    seen: set[tuple[str, str]] = set()
    with output_path.open("w", encoding="utf-8", newline="\n") as destination:
        for relation in relations:
            if relation.get("download_status") != "success":
                skipped["download_not_success"] += 1
                continue
            document_id = str(relation.get("document_id") or "")
            file_id = str(relation.get("file_id") or "")
            pair = (document_id, file_id)
            if pair in seen:
                skipped["duplicate_relation"] += 1
                continue
            seen.add(pair)
            meta = metadata.get(document_id)
            merged = merged_by_file.get(file_id)
            if not meta:
                skipped["missing_metadata"] += 1
                continue
            if not merged:
                skipped["unreadable_or_unmerged"] += 1
                continue
            text_path = merged_root / Path(merged["merged_text"])
            if not text_path.exists():
                skipped["missing_merged_text"] += 1
                continue
            content = text_path.read_text(encoding="utf-8", errors="replace").strip()
            if not content:
                skipped["empty_text"] += 1
                continue
            provisions: list[dict[str, Any]] = []
            split_summary = provision_by_file.get(file_id) or {}
            provision_file = split_summary.get("provision_file")
            if provision_file:
                provision_path = provision_root / Path(provision_file)
                if provision_path.exists():
                    provision_payload = load_json(provision_path)
                    provisions = provision_payload.get("provisions") or []
            source_language = detect_text_language(content)
            languages[source_language] += 1
            source_sha = str(relation.get("sha256") or merged.get("source_sha256") or "")
            source_collection_id = str(
                meta.get("source_id") or relation.get("source_id") or "MM-MOI-LAWS"
            )
            source_record_id = str(meta.get("source_record_id") or document_id)
            record = {
                "rule_id": f"MM-MOI-D-{document_id}-{file_id}",
                "source_id": f"{source_collection_id}:{source_record_id}",
                "law_name": str(meta.get("title") or file_id),
                "content": content,
                "url": str(meta.get("source_page_url") or relation.get("detail_url") or ""),
                "status": clean_status(meta.get("legal_status")),
                "source_legal_status": str(meta.get("legal_status") or "unverified"),
                "effective_date": str(meta.get("effective_date") or ""),
                "language": source_language,
                "metadata_language_candidate": str(meta.get("source_language_candidate") or "unknown"),
                "country": "MM",
                "country_label": "Myanmar",
                "jurisdiction": str(meta.get("jurisdiction") or "Myanmar"),
                "legal_system": "civil",
                "legal_hierarchy": str(meta.get("record_kind_candidate") or "unverified"),
                "promulgating_body": str(meta.get("issuing_authority") or ""),
                "category": "national_law_portal",
                "subject_matter": "",
                "amendment_chain": [],
                "supersedes": [],
                "document_id": document_id,
                "file_id": file_id,
                "source_document_url": str(relation.get("source_url") or ""),
                "source_sha256": source_sha,
                "text_verification_status": "machine_extracted_unverified",
                "release_status": "review_required",
                "translation_status": "none",
                "authority_note": "The cited Myanmar/English source text controls. OCR and machine-split text must be checked against the source PDF before legal reliance.",
                "quality_flags": list(meta.get("quality_flags") or []),
                "provenance": {
                    "source_page_url": meta.get("source_page_url") or "",
                    "source_document_url": relation.get("source_url") or "",
                    "source_sha256": source_sha,
                    "source_record_id": meta.get("source_record_id") or "",
                    "source_collection_id": source_collection_id,
                    "document_class": merged.get("document_class") or "",
                    "page_count": merged.get("page_count"),
                    "ocr_replaced_pages": merged.get("ocr_replaced_pages"),
                    "embedded_text_pages": merged.get("embedded_text_pages"),
                    "merged_text_file": merged.get("merged_text") or "",
                    "provision_split_status": split_summary.get("status") or "not_available",
                },
                "provisions": provisions,
            }
            destination.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            written += 1
            provision_count += len(provisions)

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    report = {
        "status": "complete",
        "documents_written": written,
        "provision_candidates_included": provision_count,
        "languages": dict(languages),
        "skipped": dict(skipped),
        "output": str(output_path),
        "content_sha256": digest,
        "authority_policy": "source_language_controls_no_translation_generated",
        "verification_policy": "machine_extracted_and_machine_split_records_remain_review_required",
    }
    output_path.with_suffix(".report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--merged-root", type=Path, required=True)
    parser.add_argument("--provision-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "data" / "documents.jsonl")
    args = parser.parse_args()
    report = build_corpus(
        metadata_path=args.metadata,
        relations_path=args.relations,
        merged_root=args.merged_root,
        provision_root=args.provision_root,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
