"""
模块描述：大陆法系（印度尼西亚 / 泰国 / 越南）管辖库入口，re-export 检索接口。

总装按《Lawyance 管辖库工作协调规范》§2.1 从这里取六个函数；本包不注册 LLM Tool，
也不改 tools/、mcps.py、function_calling.py、mcp/pkulaw_client.py。
"""

from RAG.civil_law.search import (
    DEFAULT_LIMIT,
    ensure_civil_law_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    reset_engine,
    semantic_search,
)

__all__ = [
    "DEFAULT_LIMIT",
    "ensure_civil_law_database_ready",
    "exact_search",
    "fuzzy_search",
    "link_search",
    "reset_engine",
    "semantic_search",
]
