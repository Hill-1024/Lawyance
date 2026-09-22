from __future__ import annotations

import json

from RAG.common_law.myanmar import MyanmarLawSearchEngine


def _engine(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    record = {
        "rule_id": "MM-1",
        "source_id": "MM-MOI-LAWS",
        "law_name": "Sample Myanmar Law",
        "content": "Whole law text",
        "url": "https://example.test/law/1",
        "status": "unknown",
        "language": "en",
        "country": "MM",
        "source_sha256": "a" * 64,
        "source_document_url": "https://example.test/law.pdf",
        "document_id": "doc-1",
        "file_id": "file-1",
        "provisions": [
            {
                "provision_id": "MM-P-1",
                "provision_locator": "Section 1",
                "normalized_locator": "1",
                "original_text": "This Act may be cited as the Sample Law.",
                "page_locator": {"pdf_page_start": 1, "pdf_page_end": 1},
                "text_verification_status": "machine_split_unverified",
                "release_status": "review_required",
            }
        ],
    }
    (data_dir / "documents.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return MyanmarLawSearchEngine(data_dir=data_dir, cache_dir=tmp_path / "cache")


def test_ready_reuses_content_fingerprint(tmp_path):
    engine = _engine(tmp_path)
    result = engine.ensure_ready()
    assert result["mode"] == "reuse"
    assert result["document_count"] == 1
    assert result["entry_count"] == 1


def test_exact_fuzzy_and_link_envelopes(tmp_path):
    engine = _engine(tmp_path)
    exact = json.loads(engine.exact_search("Sample Myanmar Law", "Section 1"))
    assert exact["success"] is True
    assert exact["data"]["article_number"] == "1"
    assert exact["data"]["country"] == "MM"
    assert exact["data"]["release_status"] == "review_required"

    fuzzy = json.loads(engine.fuzzy_search("cited", 50))
    assert fuzzy["success"] is True
    assert fuzzy["returned_count"] == 1
    assert fuzzy["data"][0]["source_sha256"] == "a" * 64

    linked = json.loads(engine.link_search("Sample Myanmar Law Section 1", 1))
    assert linked["success"] is True
    assert linked["references"][0]["title"] == "Sample Myanmar Law"
    assert linked["data"][0]["rule_id"] == "doc-1:MM-P-1"


def test_empty_inputs_return_failures(tmp_path):
    engine = _engine(tmp_path)
    assert json.loads(engine.exact_search("", "1"))["success"] is False
    assert json.loads(engine.fuzzy_search("", 5))["success"] is False
