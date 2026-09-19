from __future__ import annotations

import json
from pathlib import Path

from RAG.singapore_law import (
    ensure_singapore_law_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    reset_engine,
    semantic_search,
)


TITLE = "Central Provident Fund (Amendment) Act 2026"


def decode(value: str) -> dict:
    assert isinstance(value, str)
    return json.loads(value)


def test_seed_contract_and_provenance() -> None:
    seed_path = Path("RAG/singapore_law/data/official_seed.json")
    records = json.loads(seed_path.read_text(encoding="utf-8"))
    assert len(records) == 10
    assert len({item["rule_id"] for item in records}) == 10
    for item in records:
        for key in ("law_name", "article_number", "content", "url"):
            assert item[key]
        assert item["language"] == "en"
        assert item["country"] == "SG"
        assert item["jurisdiction"] == "Singapore"
        assert item["legal_system"] == "common"
        assert item["status"] == "unknown"
        assert len(item["source_sha256"]) == 64
        assert len(item["source_text_sha256"]) == 64
        assert item["translation_notice"]


def test_readiness_is_deterministic() -> None:
    first = ensure_singapore_law_database_ready(force_rebuild=True)
    second = ensure_singapore_law_database_ready()
    assert first["mode"] == "full"
    assert second["mode"] == "unchanged"
    assert first["content_sha256"] == second["content_sha256"]
    assert first["schema_version"] == "1.0.0"
    assert first["record_count"] == 10


def test_exact_search_normalizes_section_notation() -> None:
    reset_engine()
    result = decode(exact_search(TITLE, "第1条"))
    assert result["success"] is True
    assert result["data"]["rule_id"] == "SG-EGAZETTE-2026-ACT14-SEC1"
    assert result["data"]["url"].startswith("https://assets.egazette.gov.sg/")


def test_exact_search_miss_uses_exact_envelope() -> None:
    result = decode(exact_search(TITLE, "section 999"))
    assert result["success"] is False
    assert result["data"] is None
    assert isinstance(result["search_time"], float)


def test_fuzzy_and_semantic_envelopes() -> None:
    fuzzy = decode(fuzzy_search("中央公积金 投资", limit=200))
    assert fuzzy["success"] is True
    assert 1 <= fuzzy["returned_count"] <= 20
    assert fuzzy["total_count"] >= fuzzy["returned_count"]
    assert any(item["law_name"] == TITLE for item in fuzzy["data"])

    semantic = decode(semantic_search("energy conservation", limit=2))
    assert semantic["success"] is True
    assert semantic["returned_count"] <= 2


def test_link_search_returns_compatible_references_and_data() -> None:
    result = decode(link_search(f"Use {TITLE}, s. 2"))
    assert result["success"] is True
    assert result["text"]
    assert len(result["references"]) == 1
    assert len(result["data"]) == 1
    reference = result["references"][0]
    assert set(("title", "article_number", "url", "content")) <= set(reference)
    assert reference["article_number"] == "section 2"
    assert result["data"][0]["rule_id"] == "SG-EGAZETTE-2026-ACT14-SEC2"
