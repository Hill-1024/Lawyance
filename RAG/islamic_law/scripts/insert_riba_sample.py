#!/usr/bin/env python3
"""
P1 种子脚本：初始化双层伊斯兰法库，写入：
- 共享层原则 SH-PRINCIPLE-RIBA-001
- 马来西亚 IFSA 2013 riba 合规链条（AGC 官方 PDF 核验条款）
- 马来西亚 CBA 2009 ss.56–58（SAC 提交、拘束力、优先）
- BNM SAC riba 相关裁决（2010 汇编核对副本 + 第210/213次会议官网摘要）
- 共享层经训：Quran 2:275–279（阿/英/中）+ 已核圣训编号
- 共享层扩展：gharar / maysir / sukuk / takaful / halal-haram / governance（religious-guidance）
- 马来西亚正式综合条目 MY-RIBA-IFSA-2013-001（record_grade=formal）
- 马来西亚第二批正式条目（sukuk / takaful / IFSA 治理 / SGP / halal，record_grade=formal）
- 印尼halal 核心正式条目（UU 33/2014、PP 42/2024、BPJPH 2026-10-18，record_grade=formal）
- 四语术语表初版
- 权威来源白名单
- manifest.shared.json + manifest.country.MY.json + manifest.country.ID.json

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.islamic_law.countries import (  # noqa: E402
    ASEAN_COUNTRY_TIERS,
    country_display_name,
)
from RAG.islamic_law.models import (  # noqa: E402
    INSERT_AUTHORITY_SQL,
    IslamicRule,
    ShariaPrinciple,
    TermEntry,
    insert_principles,
    insert_rules,
    insert_terms,
)

BASE = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE / "schema.sql"
CACHE_DIR = BASE / "cache"
DB_PATH = CACHE_DIR / "islamic_rules.db"
MANIFEST_SHARED = CACHE_DIR / "manifest.shared.json"
MANIFEST_MY = CACHE_DIR / "manifest.country.MY.json"
MANIFEST_ID = CACHE_DIR / "manifest.country.ID.json"

SCHEMA_VERSION = 3


CORE_TERMS: list[TermEntry] = [
    TermEntry("riba", en="riba", zh="利息/高利贷", preferred_zh="里巴（禁止利息）", ar="ربا", ms="riba", id="riba", aliases=["利息", "高利贷", "usury", "interest"]),
    TermEntry("gharar", en="gharar", zh="不确定性/过度投机", preferred_zh="格哈拉尔", ar="غرر", ms="gharar", id="gharar", aliases=["不确定性", "过度风险"]),
    TermEntry("maysir", en="maysir", zh="博彩/赌博", preferred_zh="迈西尔", ar="ميسر", ms="maysir", id="maysir", aliases=["赌博", "博彩", "gambling"]),
    TermEntry("sukuk", en="sukuk", zh="伊斯兰债券", preferred_zh="苏库克", ar="صكوك", ms="sukuk", id="sukuk", aliases=["伊斯兰收益凭证", "Islamic bond"]),
    TermEntry("takaful", en="takaful", zh="伊斯兰保险", preferred_zh="塔卡富尔", ar="تكافل", ms="takaful", id="takaful", aliases=["互助保险"]),
    TermEntry("ijarah", en="ijarah", zh="租赁", preferred_zh="伊贾拉（租赁）", ar="إجارة", ms="ijarah", id="ijarah", aliases=["leasing"]),
    TermEntry("murabahah", en="murabahah", zh="成本加利润销售", preferred_zh="穆拉巴哈", ar="مرابحة", ms="murabahah", id="murabahah", aliases=["成本加成销售"]),
    TermEntry("mudarabah", en="mudarabah", zh="盈亏合伙（出资-经营）", preferred_zh="穆达拉巴", ar="مضاربة", ms="mudarabah", id="mudarabah", aliases=["盈亏分成"]),
    TermEntry("musharakah", en="musharakah", zh="合资合伙", preferred_zh="穆沙拉卡", ar="مشاركة", ms="musharakah", id="musharakah", aliases=["合伙"]),
    TermEntry("wakalah", en="wakalah", zh="代理", preferred_zh="瓦卡拉（代理）", ar="وكالة", ms="wakalah", id="wakalah", aliases=["agency"]),
    TermEntry("kafalah", en="kafalah", zh="保证/担保", preferred_zh="卡法拉", ar="كفالة", ms="kafalah", id="kafalah", aliases=["guarantee"]),
    TermEntry("waqf", en="waqf", zh="宗教捐赠/卧各夫", preferred_zh="卧各夫", ar="وقف", ms="wakaf", id="wakaf", aliases=["wakaf", "宗教基金"]),
    TermEntry("zakat", en="zakat", zh="天课", preferred_zh="天课", ar="زكاة", ms="zakat", id="zakat", aliases=["天课税"]),
    TermEntry("faraid", en="faraid", zh="固定继承份额", preferred_zh="法拉伊德", ar="فرائض", ms="faraid", id="faraid", aliases=["伊斯兰继承"]),
    TermEntry("muamalat", en="muamalat", zh="商事交易", preferred_zh="穆阿马拉特", ar="معاملات", ms="muamalat", id="muamalat", aliases=["商事"]),
    TermEntry("fatwa", en="fatwa", zh="法特瓦", preferred_zh="法特瓦", ar="فتوى", ms="fatwa", id="fatwa", aliases=["教法意见"]),
    TermEntry("qanun", en="qanun", zh="卡农/特区条例", preferred_zh="卡农", ar="قانون", ms="qanun", id="qanun", aliases=["亚齐条例"]),
    TermEntry("halal", en="halal", zh="清真/合法", preferred_zh="哈拉勒", ar="حلال", ms="halal", id="halal", aliases=["清真"]),
    TermEntry("haram", en="haram", zh="禁止/不合法", preferred_zh="哈拉姆", ar="حرام", ms="haram", id="haram", aliases=["禁忌"]),
]


AUTHORITY_SOURCES = [
    {
        "source_key": "MY-AGC-LOM",
        "country": "MY",
        "layer": "country",
        "organization": "Attorney General's Chambers (Laws of Malaysia)",
        "channels": "Federal legislation reprints / official PDF portal",
        "primary_use": "IFSA 2013 等联邦法律官方文本",
        "homepage_url": "https://lom.agc.gov.my/",
        "notes": "AGC reprint 声明 NOT AN AUTHENTIC TEXT；仍为官方对外发布门户",
    },
    {
        "source_key": "MY-BNM",
        "country": "MY",
        "layer": "country",
        "organization": "Bank Negara Malaysia (BNM)",
        "channels": "SAC rulings, IFSA-related guidance",
        "primary_use": "伊斯兰金融监管与 SAC 裁决",
        "homepage_url": "https://www.bnm.gov.my/",
        "notes": "SAC 汇编 2nd ed. 2010 本地为内容核对副本；正式引用请对照 bnm.gov.my 官方 PDF",
    },
    {
        "source_key": "MY-SC",
        "country": "MY",
        "layer": "country",
        "organization": "Securities Commission Malaysia",
        "channels": "SC SAC, Shariah screening",
        "primary_use": "资本市场 Shariah 筛查与 sukuk",
        "homepage_url": "https://www.sc.com.my/",
        "notes": "",
    },
    {
        "source_key": "MY-JAKIM",
        "country": "MY",
        "layer": "country",
        "organization": "JAKIM",
        "channels": "halal certification",
        "primary_use": "halal 事务",
        "homepage_url": "https://www.halal.gov.my/",
        "notes": "",
    },
    {
        "source_key": "ID-DSN-MUI",
        "country": "ID",
        "layer": "country",
        "organization": "DSN-MUI",
        "channels": "numbered fatwa",
        "primary_use": "法特瓦；经 OJK/BI 吸收后可能升格约束力",
        "homepage_url": "https://dsnmui.or.id/",
        "notes": "",
    },
    {
        "source_key": "ID-OJK",
        "country": "ID",
        "layer": "country",
        "organization": "OJK",
        "channels": "financial regulation",
        "primary_use": "金融监管吸收法特瓦",
        "homepage_url": "https://www.ojk.go.id/",
        "notes": "",
    },
    {
        "source_key": "ID-BPJPH",
        "country": "ID",
        "layer": "country",
        "organization": "BPJPH",
        "channels": "halal certification",
        "primary_use": "清真产品保障与认证",
        "homepage_url": "https://bpjph.halal.go.id/",
        "notes": "关注 2026-10-18 强制节点",
    },
    {
        "source_key": "BN-AGC",
        "country": "BN",
        "layer": "country",
        "organization": "Attorney General's Chambers Brunei",
        "channels": "legislation",
        "primary_use": "立法文本",
        "homepage_url": "https://www.agc.gov.bn/",
        "notes": "",
    },
    {
        "source_key": "SG-MUIS",
        "country": "SG",
        "layer": "country",
        "organization": "MUIS",
        "channels": "fatwa, halal, AMLA administration",
        "primary_use": "法特瓦与穆斯林事务",
        "homepage_url": "https://www.muis.gov.sg/",
        "notes": "",
    },
    {
        "source_key": "INT-AAOIFI",
        "country": "XX",
        "layer": "shared-advisory",
        "organization": "AAOIFI",
        "channels": "Shariah / accounting standards",
        "primary_use": "学理与行业标准参考，不构成国内法",
        "homepage_url": "https://aaoifi.com/",
        "notes": "legal_effect=religious-guidance",
    },
    {
        "source_key": "INT-IFSB",
        "country": "XX",
        "layer": "shared-advisory",
        "organization": "IFSB",
        "channels": "prudential standards",
        "primary_use": "监管标准参考，非国法",
        "homepage_url": "https://www.ifsb.org/",
        "notes": "",
    },
    {
        "source_key": "INT-TANZIL",
        "country": "XX",
        "layer": "shared",
        "organization": "Tanzil Project / quran.com",
        "channels": "Uthmani Quran text and published translations",
        "primary_use": "共享层经文阿语与通行译文坐标",
        "homepage_url": "https://tanzil.net/",
        "notes": "阿语权威文本层；英/中译为辅助，legal_effect=religious-guidance",
    },
    {
        "source_key": "INT-SUNNAH",
        "country": "XX",
        "layer": "shared",
        "organization": "sunnah.com",
        "channels": "Hadith collections with stable numbering URLs",
        "primary_use": "圣训集录名与现行编号核验",
        "homepage_url": "https://sunnah.com/",
        "notes": "编号以 sunnah.com 现行编号为准；未核到的条目不得编造",
    },
]


RULE_PACKS = [
    BASE / "data" / "MY" / "my_riba_ifsa_2013_formal.json",
    BASE / "data" / "MY" / "my_step3_2_formal.json",
    BASE / "data" / "MY" / "ifsa2013_riba_rules.json",
    BASE / "data" / "MY" / "ifsa2013_shariah_governance_rules.json",
    BASE / "data" / "MY" / "cba2009_sac_rules.json",
    BASE / "data" / "MY" / "bnm_sac_riba_rules.json",
    BASE / "data" / "MY" / "bnm_sac_sukuk_rules.json",
    BASE / "data" / "MY" / "bnm_sac_takaful_rules.json",
    BASE / "data" / "MY" / "bnm_sgp_2019_rules.json",
    BASE / "data" / "MY" / "jakim_halal_rules.json",
    BASE / "data" / "ID" / "id_halal_formal.json",
    BASE / "data" / "ID" / "id_halal_uu33_pp42_rules.json",
    BASE / "data" / "ID" / "id_islamic_finance_formal.json",
    BASE / "data" / "ID" / "id_islamic_finance_rules.json",
]
PRINCIPLE_PACKS = [
    BASE / "data" / "shared" / "riba_scripture_principle.json",
    BASE / "data" / "shared" / "principles_step3_1.json",
    BASE / "data" / "shared" / "principle_governance_step3_2.json",
]
FORMAL_RULE_ID = "MY-RIBA-IFSA-2013-001"
FORMAL_RULE_IDS = (
    "MY-RIBA-IFSA-2013-001",
    "MY-SUKUK-BNM-SAC-001",
    "MY-TAKAFUL-BNM-SAC-001",
    "MY-IFSA-2013-GOV-S28-29-001",
    "MY-IFSA-2013-GOV-S30-38-001",
    "MY-BNM-SGP-2019-FORMAL-001",
    "MY-HALAL-ACT730-FORMAL-001",
    "MY-HALAL-MS1500-FORMAL-001",
    "ID-HALAL-UU33-2014-001",
    "ID-HALAL-PP42-2024-001",
    "ID-HALAL-BPJPH-2026-001",
    "ID-HALAL-JPH-CORE-001",
    "ID-FIN-MUI-BUNGA-2004-001",
    "ID-FIN-UU21-2008-001",
    "ID-FIN-POJK16-2022-001",
    "ID-FIN-POJK18-2015-001",
)
FORMAL_PRINCIPLE_BY_RULE = {
    "MY-RIBA-IFSA-2013-001": "SH-PRINCIPLE-RIBA-001",
    "MY-SUKUK-BNM-SAC-001": "SH-PRINCIPLE-SUKUK-001",
    "MY-TAKAFUL-BNM-SAC-001": "SH-PRINCIPLE-TAKAFUL-001",
    "MY-IFSA-2013-GOV-S28-29-001": "SH-PRINCIPLE-GOVERNANCE-001",
    "MY-IFSA-2013-GOV-S30-38-001": "SH-PRINCIPLE-GOVERNANCE-001",
    "MY-BNM-SGP-2019-FORMAL-001": "SH-PRINCIPLE-GOVERNANCE-001",
    "MY-HALAL-ACT730-FORMAL-001": "SH-PRINCIPLE-HALAL-HARAM-001",
    "MY-HALAL-MS1500-FORMAL-001": "SH-PRINCIPLE-HALAL-HARAM-001",
    "ID-HALAL-UU33-2014-001": "SH-PRINCIPLE-HALAL-HARAM-001",
    "ID-HALAL-PP42-2024-001": "SH-PRINCIPLE-HALAL-HARAM-001",
    "ID-HALAL-BPJPH-2026-001": "SH-PRINCIPLE-HALAL-HARAM-001",
    "ID-HALAL-JPH-CORE-001": "SH-PRINCIPLE-HALAL-HARAM-001",
    "ID-FIN-MUI-BUNGA-2004-001": "SH-PRINCIPLE-RIBA-001",
    "ID-FIN-UU21-2008-001": "SH-PRINCIPLE-RIBA-001",
    "ID-FIN-POJK16-2022-001": "SH-PRINCIPLE-RIBA-001",
    "ID-FIN-POJK18-2015-001": "SH-PRINCIPLE-SUKUK-001",
}
FORMAL_REQUIRED_FIELDS = (
    "rule_id",
    "source_id",
    "law_name",
    "article_number",
    "content",
    "url",
    "status",
    "effective_date",
    "language",
    "country",
    "country_label",
    "rule_subject",
    "national_transformation",
    "parallel_languages",
    "output_annotation",
    "madhhab",
    "sharia_source_type",
    "religious_anchor",
    "fatwa_issuer",
    "fatwa_id",
    "supersedes",
    "legal_effect",
    "applicability_person",
    "applicability_subject",
    "applicability_territory",
    "arabic_text",
    "transliteration",
    "sharia_principle_id",
    "country_rule_ids",
)


def load_rule_pack(path: Path) -> list[IslamicRule]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing rule pack: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Expected non-empty list in {path}")
    allowed = {f.name for f in fields(IslamicRule)}
    rules: list[IslamicRule] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"Expected object entries in {path}")
        rules.append(IslamicRule(**{k: v for k, v in item.items() if k in allowed}))
    return rules


def load_country_rules() -> list[IslamicRule]:
    rules: list[IslamicRule] = []
    seen: set[str] = set()
    for path in RULE_PACKS:
        for rule in load_rule_pack(path):
            if rule.rule_id in seen:
                raise ValueError(f"Duplicate rule_id {rule.rule_id} in {path}")
            seen.add(rule.rule_id)
            rules.append(rule)
    return rules


def assert_formal_rule_complete(rules: list[IslamicRule]) -> IslamicRule:
    by_id = {rule.rule_id: rule for rule in rules}
    missing_ids = [rid for rid in FORMAL_RULE_IDS if rid not in by_id]
    if missing_ids:
        raise ValueError(f"Missing formal rules: {', '.join(missing_ids)}")
    for rid in FORMAL_RULE_IDS:
        formal = by_id[rid]
        missing = []
        for name in FORMAL_REQUIRED_FIELDS:
            value = getattr(formal, name)
            if value is None or value == "" or value == []:
                missing.append(name)
        if missing:
            raise ValueError(f"{rid} has empty fields: {', '.join(missing)}")
        if formal.legal_effect != "binding":
            raise ValueError(f"{rid} legal_effect must be binding, got {formal.legal_effect!r}")
        expected_principle = FORMAL_PRINCIPLE_BY_RULE[rid]
        if formal.sharia_principle_id != expected_principle:
            raise ValueError(
                f"{rid} sharia_principle_id must be {expected_principle}, "
                f"got {formal.sharia_principle_id!r}"
            )
        for name in (
            "applicability_person",
            "applicability_subject",
            "applicability_territory",
        ):
            if not getattr(formal, name):
                raise ValueError(f"{rid} missing triple-scope field {name}")
        if "record_grade=formal" not in formal.content and "record_grade=formal" not in formal.output_annotation:
            raise ValueError(f"{rid} must mark record_grade=formal")
        if not formal.url.startswith("http"):
            raise ValueError(f"{rid} must have official http(s) URL")
    return by_id[FORMAL_RULE_ID]


def load_principle_pack(path: Path) -> list[ShariaPrinciple]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing principle pack: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    items: list[dict]
    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError(f"Expected object or list in {path}")
    if not items:
        raise ValueError(f"Empty principle pack: {path}")
    allowed = {f.name for f in fields(ShariaPrinciple)}
    principles: list[ShariaPrinciple] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"Expected object entries in {path}")
        data = {k: v for k, v in item.items() if k in allowed}
        data.setdefault("country_rule_ids", [])
        data.pop("search_blob", None)
        principles.append(ShariaPrinciple(**data))
    return principles


def load_shared_principles(rules: list[IslamicRule]) -> list[ShariaPrinciple]:
    linked: dict[str, list[str]] = {}
    for rule in rules:
        pid = rule.sharia_principle_id
        if not pid:
            continue
        linked.setdefault(pid, [])
        if rule.rule_id not in linked[pid]:
            linked[pid].append(rule.rule_id)

    principles: list[ShariaPrinciple] = []
    seen: set[str] = set()
    for path in PRINCIPLE_PACKS:
        for principle in load_principle_pack(path):
            if principle.sharia_principle_id in seen:
                raise ValueError(f"Duplicate principle {principle.sharia_principle_id} in {path}")
            seen.add(principle.sharia_principle_id)
            if principle.sharia_principle_id in linked:
                principle.country_rule_ids = list(linked[principle.sharia_principle_id])
                principle.search_blob = principle.build_search_blob()
            if principle.legal_effect != "religious-guidance":
                raise ValueError(
                    f"{principle.sharia_principle_id} must be religious-guidance, "
                    f"got {principle.legal_effect!r}"
                )
            principles.append(principle)
    return principles


def build_riba_principle(country_rule_ids: list[str]) -> ShariaPrinciple:
    """Backward-compatible helper: return the riba shared principle. """
    # Minimal synthetic rules list for helper callers.
    class _Tmp:
        def __init__(self, rid: str):
            self.rule_id = rid
            self.sharia_principle_id = "SH-PRINCIPLE-RIBA-001"

    principles = load_shared_principles([_Tmp(x) for x in country_rule_ids])
    for principle in principles:
        if principle.sharia_principle_id == "SH-PRINCIPLE-RIBA-001":
            return principle
    raise ValueError("SH-PRINCIPLE-RIBA-001 missing")


def init_database(db_path: Path = DB_PATH) -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifests(principles: list[ShariaPrinciple], rules: list[IslamicRule]) -> None:
    shared = {
        "schema_version": SCHEMA_VERSION,
        "layer": "shared",
        "db_path": "cache/islamic_rules.db",
        "schema_file": "schema.sql",
        "schema_sha256": _file_sha256(SCHEMA_PATH),
        "principle_ids": [p.sharia_principle_id for p in principles],
        "term_count": len(CORE_TERMS),
        "authority_source_count": len(AUTHORITY_SOURCES),
        "asean_tiers": {
            code: meta["tier"] for code, meta in ASEAN_COUNTRY_TIERS.items()
        },
        "source_packs": [
            "sources/shared/scripture_riba/provenance.step2_4.json",
            "sources/shared/principles_step3_1/provenance.step3_1.json",
            "sources/shared/governance_step3_2/provenance.step3_2.json",
        ],
        "note": (
            "Shared layer holds religious-guidance principles only "
            "(riba, gharar, maysir, sukuk, takaful, halal/haram, governance). "
            "Not alone a country compliance basis."
        ),
    }
    country_my = {
        "schema_version": SCHEMA_VERSION,
        "layer": "country",
        "country": "MY",
        "country_label": country_display_name("MY"),
        "tier": ASEAN_COUNTRY_TIERS["MY"]["tier"],
        "db_path": "cache/islamic_rules.db",
        "rule_ids": [rule.rule_id for rule in rules],
        "sharia_principle_ids": sorted(
            {rule.sharia_principle_id for rule in rules if rule.sharia_principle_id}
        ),
        "formal_rule_ids": list(FORMAL_RULE_IDS),
        "source_packs": [
            "sources/MY/ifsa2013/provenance.step1_1.json",
            "sources/MY/cba2009/provenance.step2_2.json",
            "sources/MY/bnm_sac/provenance.step2_3.json",
            "sources/MY/bnm_sac/provenance.step3_2_sukuk_takaful.json",
            "sources/shared/scripture_riba/provenance.step2_4.json",
            "sources/MY/formal/provenance.step2_5.json",
            "sources/shared/principles_step3_1/provenance.step3_1.json",
            "sources/shared/governance_step3_2/provenance.step3_2.json",
            "sources/MY/sgp2019/provenance.step3_2.json",
            "sources/MY/halal_jakim/provenance.step3_2.json",
            "sources/MY/formal_step3_2/provenance.step3_2.json",
        ],
        "formal_rule_id": FORMAL_RULE_ID,
        "note": (
            "MY country layer: riba formal + step 3.2 finance formal set "
            "(sukuk/takaful/IFSA governance/SGP/halal)."
        ),
    }
    my_rules = [rule for rule in rules if rule.country == "MY"]
    id_rules = [rule for rule in rules if rule.country == "ID"]
    id_formal_ids = [rid for rid in FORMAL_RULE_IDS if rid.startswith("ID-")]
    my_formal_ids = [rid for rid in FORMAL_RULE_IDS if rid.startswith("MY-")]

    country_my["rule_ids"] = [rule.rule_id for rule in my_rules]
    country_my["sharia_principle_ids"] = sorted(
        {rule.sharia_principle_id for rule in my_rules if rule.sharia_principle_id}
    )
    country_my["formal_rule_ids"] = my_formal_ids

    country_id = {
        "schema_version": SCHEMA_VERSION,
        "layer": "country",
        "country": "ID",
        "country_label": country_display_name("ID"),
        "tier": ASEAN_COUNTRY_TIERS["ID"]["tier"],
        "db_path": "cache/islamic_rules.db",
        "rule_ids": [rule.rule_id for rule in id_rules],
        "sharia_principle_ids": sorted(
            {rule.sharia_principle_id for rule in id_rules if rule.sharia_principle_id}
        ),
        "formal_rule_ids": id_formal_ids,
        "source_packs": [
            "sources/ID/halal_bpjph/provenance.step4_1.json",
            "sources/ID/islamic_finance/provenance.step4_2.json",
            "sources/shared/principles_step3_1/provenance.step3_1.json",
        ],
        "mandatory_halal_node": {
            "transition_end": "2026-10-17",
            "mandatory_start": "2026-10-18",
            "note": "2026-10-18 全面强制、官方不再延期",
        },
        "islamic_finance_chain": (
            "Fatwa MUI 1/2004 → UU 21/2008 → POJK 16/2022 (BUS) + POJK 18/2015 (Sukuk)"
        ),
        "note": (
            "ID country layer: step 4.1 halal core (UU 33/2014 + PP 42/2024 + BPJPH 2026-10-18) "
            "and step 4.2 Islamic finance (Fatwa MUI 1/2004 + UU 21/2008 + POJK 16/2022 + "
            "POJK 18/2015); Bahasa Indonesia official texts prevail."
        ),
    }

    MANIFEST_SHARED.write_text(json.dumps(shared, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_MY.write_text(json.dumps(country_my, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_ID.write_text(json.dumps(country_id, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    rules = load_country_rules()
    formal = assert_formal_rule_complete(rules)
    principles = load_shared_principles(rules)
    conn = init_database()
    try:
        n_p = insert_principles(conn, principles)
        n_r = insert_rules(conn, rules)
        n_t = insert_terms(conn, CORE_TERMS)
        for row in AUTHORITY_SOURCES:
            conn.execute(INSERT_AUTHORITY_SQL, row)
        conn.execute(
            "INSERT OR REPLACE INTO islamic_manifest(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO islamic_manifest(key, value) VALUES (?, ?)",
            ("seed", "id_islamic_finance_step4_2"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO islamic_manifest(key, value) VALUES (?, ?)",
            ("formal_rule_id", FORMAL_RULE_ID),
        )
        conn.execute(
            "INSERT OR REPLACE INTO islamic_manifest(key, value) VALUES (?, ?)",
            ("formal_rule_ids", json.dumps(list(FORMAL_RULE_IDS), ensure_ascii=False)),
        )
        conn.commit()
        write_manifests(principles, rules)

        preview = conn.execute(
            """
            SELECT r.rule_id, r.article_number, r.legal_effect, r.sharia_source_type
            FROM islamic_rules r
            ORDER BY r.rule_id
            """
        ).fetchall()
        formal_rows = conn.execute(
            f"""
            SELECT rule_id, legal_effect, sharia_principle_id, url,
                   length(arabic_text) AS ar_len
            FROM islamic_rules
            WHERE rule_id IN ({",".join("?" for _ in FORMAL_RULE_IDS)})
            ORDER BY rule_id
            """,
            tuple(FORMAL_RULE_IDS),
        ).fetchall()
        principle_rows = conn.execute(
            """
            SELECT sharia_principle_id, legal_effect, rule_subject,
                   length(arabic_text) AS ar_len, length(content) AS content_len
            FROM sharia_principles
            ORDER BY sharia_principle_id
            """
        ).fetchall()
        auth_count = conn.execute("SELECT COUNT(*) FROM authority_sources").fetchone()[0]

        print(f"Database: {DB_PATH}")
        print(f"Inserted principles={n_p} rules={n_r} terms={n_t} authorities={auth_count}")
        print(f"Manifest shared: {MANIFEST_SHARED}")
        print(f"Manifest MY: {MANIFEST_MY}")
        print(f"Manifest ID: {MANIFEST_ID}")
        print(f"Formal entries ({len(formal_rows)}):")
        for formal_row in formal_rows:
            print(
                f"  {formal_row['rule_id']}  {formal_row['legal_effect']}  "
                f"{formal_row['sharia_principle_id']}  url_ok={str(formal_row['url']).startswith('http')}"
            )
        print(f"Anchor formal still present: {formal.rule_id}")
        print("Principles:")
        for row in principle_rows:
            print(
                f"  {row['sharia_principle_id']}  {row['legal_effect']}  "
                f"ar={row['ar_len']}  {row['rule_subject']}"
            )
        print(f"Rules: {len(preview)} total")
        for row in preview:
            if row["rule_id"] in FORMAL_RULE_IDS or "CHAIN" in row["rule_id"]:
                print(
                    f"  {row['rule_id']}  {row['article_number']}  "
                    f"{row['legal_effect']}  {row['sharia_source_type']}"
                )

        # 对齐主库：种子完成后写语料指纹，供 ensure_*_ready 判断是否需重建
        from RAG.islamic_law.search import MANIFEST_BUILD, build_source_manifest

        build_manifest = build_source_manifest()
        MANIFEST_BUILD.write_text(
            json.dumps(build_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Build manifest: {MANIFEST_BUILD} sha={build_manifest['content_sha256'][:12]}...")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
