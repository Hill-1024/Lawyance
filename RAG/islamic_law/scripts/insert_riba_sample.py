#!/usr/bin/env python3
"""
P1 种子脚本：初始化双层伊斯兰法库，写入：
- 共享层原则 SH-PRINCIPLE-RIBA-001
- 马来西亚 IFSA 2013 riba 合规链条（AGC 官方 PDF 核验条款）
- BNM SAC Resolution 81（采集记录摘录；本地未存 BNM PDF）
- 四语术语表初版
- 权威来源白名单
- manifest.shared.json + manifest.country.MY.json

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
        "notes": "P1 权威白名单；SAC Resolution 81 正式引用前须对照 BNM 官方 PDF",
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
]


IFSA_RULES_PATH = BASE / "data" / "MY" / "ifsa2013_riba_rules.json"


def load_ifsa_riba_rules() -> list[IslamicRule]:
    if not IFSA_RULES_PATH.is_file():
        raise FileNotFoundError(f"Missing IFSA rule pack: {IFSA_RULES_PATH}")
    payload = json.loads(IFSA_RULES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Expected non-empty list in {IFSA_RULES_PATH}")
    allowed = {f.name for f in fields(IslamicRule)}
    rules: list[IslamicRule] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"Expected object entries in {IFSA_RULES_PATH}")
        rules.append(IslamicRule(**{k: v for k, v in item.items() if k in allowed}))
    return rules


def build_riba_principle(country_rule_ids: list[str]) -> ShariaPrinciple:
    return ShariaPrinciple(
        sharia_principle_id="SH-PRINCIPLE-RIBA-001",
        rule_subject="禁止 riba（利息、高利贷）",
        content=(
            "伊斯兰教法禁止 riba。"
            "权威文本为阿语经训；本条为共享层原则记录，"
            "不得单独作为东盟任一国家的合规结论依据，须引用国家转化实例"
            "（马来西亚见 IFSA 2013 ss.28, 29, 152, 153, 167, 168 及 BNM SAC 裁决）。"
            "经训阿语原文与 A 级译文待核验后写入。"
        ),
        madhhab="Shafi'i",
        sharia_source_type="Quran",
        religious_anchor=(
            "《古兰经》al-Baqarah 2:275-279（阿语原文加英、中译文须 A 级人工复核后写入）；"
            "圣训依据（集录与编号待采集核验）"
        ),
        arabic_text="",
        transliteration="",
        legal_effect="religious-guidance",
        parallel_languages="阿拉伯语、马来语、印尼语、英文、中文",
        url="",
        country_rule_ids=country_rule_ids,
    )


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


def write_manifests(principle: ShariaPrinciple, rules: list[IslamicRule]) -> None:
    shared = {
        "schema_version": SCHEMA_VERSION,
        "layer": "shared",
        "db_path": "cache/islamic_rules.db",
        "schema_file": "schema.sql",
        "schema_sha256": _file_sha256(SCHEMA_PATH),
        "principle_ids": [principle.sharia_principle_id],
        "term_count": len(CORE_TERMS),
        "authority_source_count": len(AUTHORITY_SOURCES),
        "asean_tiers": {
            code: meta["tier"] for code, meta in ASEAN_COUNTRY_TIERS.items()
        },
        "note": "Shared layer remains religious-guidance until Arabic A-grade texts are verified.",
    }
    country_my = {
        "schema_version": SCHEMA_VERSION,
        "layer": "country",
        "country": "MY",
        "country_label": country_display_name("MY"),
        "tier": ASEAN_COUNTRY_TIERS["MY"]["tier"],
        "db_path": "cache/islamic_rules.db",
        "rule_ids": [rule.rule_id for rule in rules],
        "sharia_principle_ids": [principle.sharia_principle_id],
        "source_pack": "sources/MY/ifsa2013/provenance.step1_1.json",
        "note": (
            "IFSA 2013 riba chain imported from AGC official PDFs (MD5 verified). "
            "SAC Resolution 81 quoted from collection record; BNM PDF not stored locally."
        ),
    }
    MANIFEST_SHARED.write_text(json.dumps(shared, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_MY.write_text(json.dumps(country_my, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    rules = load_ifsa_riba_rules()
    principle = build_riba_principle([rule.rule_id for rule in rules])
    conn = init_database()
    try:
        n_p = insert_principles(conn, [principle])
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
            ("seed", "ifsa2013_riba_step1_1"),
        )
        conn.commit()
        write_manifests(principle, rules)

        preview = conn.execute(
            """
            SELECT r.rule_id, r.article_number, r.legal_effect, r.sharia_source_type
            FROM islamic_rules r
            ORDER BY r.rule_id
            """
        ).fetchall()
        auth_count = conn.execute("SELECT COUNT(*) FROM authority_sources").fetchone()[0]

        print(f"Database: {DB_PATH}")
        print(f"Inserted principles={n_p} rules={n_r} terms={n_t} authorities={auth_count}")
        print(f"Manifest shared: {MANIFEST_SHARED}")
        print(f"Manifest MY: {MANIFEST_MY}")
        print("Rules:")
        for row in preview:
            print(f"  {row['rule_id']}  {row['article_number']}  {row['legal_effect']}  {row['sharia_source_type']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
