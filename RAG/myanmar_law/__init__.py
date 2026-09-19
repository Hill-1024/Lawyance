"""Myanmar law database public API.

The package intentionally exposes the same small API used by the other
Lawyance jurisdiction databases.  Tool registration belongs to the assembly
layer and is deliberately not performed here.
"""

from .search import (
    ensure_myanmar_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    reset_engine,
    semantic_search,
)

__all__ = [
    "ensure_myanmar_database_ready",
    "exact_search",
    "fuzzy_search",
    "semantic_search",
    "link_search",
    "reset_engine",
]
