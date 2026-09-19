"""Assembly-facing smoke cases for the Singapore written-law adapter."""

from __future__ import annotations

import json

from RAG.singapore_law import (
    ensure_singapore_law_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    semantic_search,
)


KNOWN_TITLE = "Central Provident Fund (Amendment) Act 2026"


def decode(value: str) -> dict:
    assert isinstance(value, str)
    decoded = json.loads(value)
    assert isinstance(decoded, dict)
    return decoded


def assert_core(record: dict) -> None:
    for key in ("law_name", "article_number", "content", "url"):
        assert key in record and str(record[key]).strip(), key
    assert record["country"] == "SG"
    assert record["legal_system"] == "common"
    assert record["language"] == "en"


def main() -> None:
    report = []

    ready = ensure_singapore_law_database_ready()
    assert ready["mode"] in {"full", "unchanged"}
    assert ready["record_count"] == 10
    report.append({"case": "ensure", "mode": ready["mode"]})

    exact = decode(exact_search(KNOWN_TITLE, "section 1"))
    assert exact["success"] is True
    assert_core(exact["data"])
    assert exact["data"]["rule_id"] == "SG-EGAZETTE-2026-ACT14-SEC1"
    report.append({"case": "exact", "rule_id": exact["data"]["rule_id"]})

    fuzzy = decode(fuzzy_search("中央公积金 投资", limit=3))
    assert fuzzy["success"] is True
    assert fuzzy["returned_count"] >= 1
    assert any(item["law_name"] == KNOWN_TITLE for item in fuzzy["data"])
    assert_core(fuzzy["data"][0])
    report.append({"case": "fuzzy_zh", "returned": fuzzy["returned_count"]})

    semantic = decode(semantic_search("securities futures regulation", limit=3))
    assert semantic["success"] is True
    assert semantic["data"]
    report.append({"case": "semantic_alias", "returned": semantic["returned_count"]})

    linked = decode(link_search(f"Please cite {KNOWN_TITLE} section 2"))
    assert linked["success"] is True
    assert linked["references"]
    assert linked["data"]
    reference = linked["references"][0]
    for key in ("title", "article_number", "url", "content"):
        assert key in reference and str(reference[key]).strip(), key
    assert reference["article_number"] == "section 2"
    assert_core(linked["data"][0])
    report.append({"case": "link", "references": len(linked["references"])})

    print(json.dumps({"status": "ALL_PASS", "cases": report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
