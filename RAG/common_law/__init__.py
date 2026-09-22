"""
模块描述：普通法系（缅甸 / 新加坡）管辖库入口，re-export 检索接口。

总装从这里取六个函数。本包不注册 LLM Tool，也不改 tools/、mcps.py。
"""

from .myanmar import ensure_myanmar_database_ready
from .search import (
    DEFAULT_LIMIT,
    ensure_common_law_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    reset_engine,
    semantic_search,
)
from .singapore import ensure_singapore_law_database_ready

__all__ = [
    "DEFAULT_LIMIT",
    "ensure_common_law_database_ready",
    "ensure_myanmar_database_ready",
    "ensure_singapore_law_database_ready",
    "exact_search",
    "fuzzy_search",
    "link_search",
    "reset_engine",
    "semantic_search",
]
