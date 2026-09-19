"""Repository-root smoke checks for the Myanmar law package."""

from __future__ import annotations

import json

from RAG.myanmar_law import (
    ensure_myanmar_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    semantic_search,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


def main() -> int:
    ready = ensure_myanmar_database_ready()
    require(ready["mode"] in {"reuse", "rebuild"}, "database_ready")
    require(ready["entry_count"] > 0, "database_has_entries")

    probe = json.loads(fuzzy_search("ဥပဒေ", 1))
    if not probe["success"]:
        probe = json.loads(fuzzy_search("law", 1))
    require(probe["success"] and probe["data"], "fuzzy_search")
    hit = probe["data"][0]
    for field in ("law_name", "article_number", "content", "url"):
        require(field in hit, f"core_field_{field}")
    require(hit.get("country") == "MM", "country_filter_integrity")
    require(hit.get("source_sha256"), "source_sha256_provenance")

    exact = json.loads(exact_search(hit["law_name"], hit["article_number"]))
    require(exact["success"], "exact_search")
    semantic = json.loads(semantic_search(hit["law_name"], 1))
    require(semantic["success"], "semantic_alias")
    linked = json.loads(link_search(hit["law_name"], 1))
    require(linked["success"] and linked["references"], "link_search")
    for field in ("title", "article_number", "url", "content"):
        require(field in linked["references"][0], f"reference_field_{field}")
    require(linked.get("data"), "link_search_full_data")
    print("ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
