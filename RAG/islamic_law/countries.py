"""
模块描述：东盟伊斯兰法相关国家标签与建库分档（核心/有限/备注）。
"""

from __future__ import annotations

from typing import Any

# ISO 3166-1 alpha-2 → 展示用 label
COUNTRY_LABELS: dict[str, str] = {
    # ASEAN 十一国
    "MY": "Malaysia",
    "ID": "Indonesia",
    "BN": "Brunei",
    "SG": "Singapore",
    "PH": "Philippines",
    "TH": "Thailand",
    "VN": "Vietnam",
    "LA": "Laos",
    "KH": "Cambodia",
    "MM": "Myanmar",
    "TL": "Timor-Leste",
    # 其他常用伊斯兰法域（非东盟建库重点）
    "SA": "Saudi Arabia",
    "AE": "United Arab Emirates",
    "QA": "Qatar",
    "KW": "Kuwait",
    "OM": "Oman",
    "BH": "Bahrain",
    "EG": "Egypt",
    "PK": "Pakistan",
    "XX": "Transnational / Comparative",
}

# 表1：东盟十一国伊斯兰法适用范围分档
ASEAN_COUNTRY_TIERS: dict[str, dict[str, str]] = {
    "MY": {
        "tier": "core",
        "tier_label": "核心档",
        "scope": (
            "双轨体制；婚姻、继承等属州立法权；伊斯兰金融为联邦事项且体系成熟，"
            "是商事建库重点"
        ),
    },
    "ID": {
        "tier": "core",
        "tier_label": "核心档",
        "scope": (
            "国家法为大陆法，sharia 经济规则经国家立法吸收；"
            "亚齐特区以 Qanun 实施较完整 Sharia；穆斯林人口最多"
        ),
    },
    "BN": {
        "tier": "core",
        "tier_label": "核心档",
        "scope": (
            "双轨体制；2013 Syariah Penal Code Order 分阶段扩大管辖；"
            "马来伊斯兰君主制"
        ),
    },
    "SG": {
        "tier": "limited",
        "tier_label": "有限档",
        "scope": (
            "AMLA 管辖穆斯林身份、家庭、wakaf、halal 与法特瓦；"
            "商事主要余 halal 与伊斯兰金融窗口"
        ),
    },
    "PH": {
        "tier": "limited",
        "tier_label": "有限档",
        "scope": "PD 1083 穆斯林个人法典；Bangsamoro 自治区另有扩展立法",
    },
    "TH": {
        "tier": "limited",
        "tier_label": "有限档",
        "scope": "仅南部部分府对穆斯林适用伊斯兰家庭与继承法，商事相关度低",
    },
    "VN": {
        "tier": "note",
        "tier_label": "备注档",
        "scope": "无制度性适用，仅保留穆斯林少数群体习俗备注",
    },
    "LA": {
        "tier": "note",
        "tier_label": "备注档",
        "scope": "无制度性适用，仅保留习俗备注",
    },
    "KH": {
        "tier": "note",
        "tier_label": "备注档",
        "scope": "无制度性适用，仅保留习俗备注",
    },
    "MM": {
        "tier": "note",
        "tier_label": "备注档",
        "scope": "无制度性适用，仅保留习俗备注",
    },
    "TL": {
        "tier": "note",
        "tier_label": "备注档",
        "scope": "无制度性适用，仅保留习俗备注",
    },
}

ALLOWED_COUNTRIES = frozenset(COUNTRY_LABELS)
ASEAN_CODES = frozenset(ASEAN_COUNTRY_TIERS)


def normalize_country(value: str | None) -> str:
    code = str(value or "").strip().upper()
    if code not in ALLOWED_COUNTRIES:
        raise ValueError(
            f"Unsupported country label {value!r}. "
            f"Use one of: {', '.join(sorted(ALLOWED_COUNTRIES))}"
        )
    return code


def country_display_name(code: str) -> str:
    return COUNTRY_LABELS.get(normalize_country(code), code)


def country_tier_info(code: str) -> dict[str, Any] | None:
    code = str(code or "").strip().upper()
    info = ASEAN_COUNTRY_TIERS.get(code)
    if not info:
        return None
    return {
        "country": code,
        "country_label": COUNTRY_LABELS.get(code, code),
        **info,
    }


def list_asean_by_tier(tier: str) -> list[str]:
    tier = str(tier or "").strip().lower()
    return sorted(
        code for code, meta in ASEAN_COUNTRY_TIERS.items() if meta["tier"] == tier
    )
