"""Singapore written-law retrieval package.

The public API is intentionally aligned with the jurisdiction database
coordination protocol. Search functions return JSON strings; the readiness
function returns a Python ``dict``.
"""

from .search import (
    ensure_singapore_law_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    reset_engine,
    semantic_search,
    singapore_law_exact_search,
    singapore_law_fuzzy_search,
    singapore_law_link_search,
)

__all__ = [
    "ensure_singapore_law_database_ready",
    "exact_search",
    "fuzzy_search",
    "semantic_search",
    "link_search",
    "reset_engine",
    "singapore_law_exact_search",
    "singapore_law_fuzzy_search",
    "singapore_law_link_search",
]
