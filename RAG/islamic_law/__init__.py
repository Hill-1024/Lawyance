"""
模块描述：伊斯兰法系管辖库对外接口（双层：共享原则 + 国家转化）。
"""

from .countries import (
    ASEAN_CODES,
    ASEAN_COUNTRY_TIERS,
    ALLOWED_COUNTRIES,
    COUNTRY_LABELS,
    country_display_name,
    country_tier_info,
    list_asean_by_tier,
)
from .models import IslamicRule, ShariaPrinciple, TermEntry, insert_principles, insert_rules, insert_terms
from .search import (
    ensure_islamic_database_ready,
    exact_search,
    link_search,
    reset_engine,
    semantic_search,
)

__all__ = [
    "ASEAN_CODES",
    "ASEAN_COUNTRY_TIERS",
    "ALLOWED_COUNTRIES",
    "COUNTRY_LABELS",
    "IslamicRule",
    "ShariaPrinciple",
    "TermEntry",
    "country_display_name",
    "country_tier_info",
    "ensure_islamic_database_ready",
    "exact_search",
    "insert_principles",
    "insert_rules",
    "insert_terms",
    "link_search",
    "list_asean_by_tier",
    "reset_engine",
    "semantic_search",
]
