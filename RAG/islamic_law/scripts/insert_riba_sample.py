#!/usr/bin/env python3
"""
P1 种子脚本：初始化双层伊斯兰法库，写入：
- 共享层原则 SH-PRINCIPLE-RIBA-001
- 马来西亚转化实例（附录 A 结构样例，scaffolding）
- 四语术语表初版
- 权威来源白名单骨架
- manifest.shared.json + manifest.country.MY.json

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
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
        "source_key": "MY-BNM",
        "country": "MY",
        "layer": "country",
        "organization": "Bank Negara Malaysia (BNM)",
        "channels": "SAC rulings, IFSA-related guidance",
        "primary_use": "伊斯兰金融监管与 SAC 裁决",
        "homepage_url": "https://www.bnm.gov.my/",
        "notes": "P1 权威白名单骨架；具体决议页采集时补全",
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


def build_riba_principle() -> ShariaPrinciple:
    return ShariaPrinciple(
        sharia_principle_id="SH-PRINCIPLE-RIBA-001",
        rule_subject="禁止 riba（利息、高利贷）",
        content=(
            "[Scaffolding / 结构样例] 伊斯兰教法禁止 riba。"
            "权威文本为阿语经训；本条为共享层原则记录，"
            "不得单独作为东盟任一国家的合规结论依据，须引用国家转化实例。"
        ),
        madhhab="Shafi'i",
        sharia_source_type="Quran",
        religious_anchor=(
            "《古兰经》al-Baqarah 2:275-279（阿语原文加英、中译文须 A 级人工复核后写入；"
            "当前为结构占位）；圣训依据（集录与编号待采集核验）"
        ),
        arabic_text="",
        transliteration="",
        legal_effect="religious-guidance",
        parallel_languages="阿拉伯语、马来语、印尼语、英文、中文",
        url="",
        country_rule_ids=["MY-RIBA-IFSA-2013-001"],
    )


def build_riba_malaysia_rule() -> IslamicRule:
    return IslamicRule(
        rule_id="MY-RIBA-IFSA-2013-001",
        source_id="my_riba_ifsa_2013_sample",
        law_name="Islamic Financial Services Act 2013",
        article_number="Central Bank of Malaysia Act 2009 Section 57",
        content=(
            "[Scaffolding / 结构样例] 禁止 riba（利息、高利贷）。"
            "马来西亚通过 IFSA 2013 与《2009 年中央银行法》第 57 条"
            "（赋予 SAC 裁决拘束力）及 BNM SAC 相关决议，"
            "将沙里亚禁止 riba 的原则转化为对持牌伊斯兰金融机构具有拘束力的监管规则。"
            "BNM SAC 届次与具体决议编号、官方链接须核验后写入正式库。"
        ),
        url="https://www.bnm.gov.my/",
        status="in_force",
        effective_date="2013-06-30",
        language="en",
        country="MY",
        country_label=country_display_name("MY"),
        rule_subject="禁止 riba（利息、高利贷）",
        national_transformation=(
            "IFSA 2013；《2009 年中央银行法》第 57 条（SAC 裁决拘束力）；"
            "BNM SAC 相关决议（届次与编号待采集核验）"
        ),
        parallel_languages="阿拉伯语、马来语、英文、中文",
        output_annotation=(
            "适用国家：马来西亚；法系：混合法系（普通法加 Shafi'i Sharia）；"
            "适用范围：持牌伊斯兰金融机构的金融业务；"
            "出处：IFSA 2013 与 BNM SAC 裁决（编号核验后补）"
        ),
        madhhab="Shafi'i（东盟主流学派，并存记录其他学派观点）",
        sharia_source_type="Statute",
        religious_anchor=(
            "《古兰经》al-Baqarah 2:275-279（译文等级待 A 级复核）；"
            "圣训依据（集录与编号待采集核验）"
        ),
        fatwa_issuer="BNM-SAC",
        fatwa_id="",
        supersedes="",
        legal_effect="binding",
        applicability_person="持牌伊斯兰金融机构及其客户",
        applicability_subject="伊斯兰金融业务",
        applicability_territory="马来西亚全境",
        arabic_text="",
        transliteration="",
        sharia_principle_id="SH-PRINCIPLE-RIBA-001",
        country_rule_ids=["MY-RIBA-IFSA-2013-001"],
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


def write_manifests(principle: ShariaPrinciple, rule: IslamicRule) -> None:
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
        "note": "Scaffolding seed; verified official texts required before production use.",
    }
    country_my = {
        "schema_version": SCHEMA_VERSION,
        "layer": "country",
        "country": "MY",
        "country_label": country_display_name("MY"),
        "tier": ASEAN_COUNTRY_TIERS["MY"]["tier"],
        "db_path": "cache/islamic_rules.db",
        "rule_ids": [rule.rule_id],
        "sharia_principle_ids": [rule.sharia_principle_id],
        "note": "Appendix A structure sample; fatwa numbers and URLs pending verification.",
    }
    MANIFEST_SHARED.write_text(json.dumps(shared, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_MY.write_text(json.dumps(country_my, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    principle = build_riba_principle()
    rule = build_riba_malaysia_rule()
    conn = init_database()
    try:
        n_p = insert_principles(conn, [principle])
        n_r = insert_rules(conn, [rule])
        n_t = insert_terms(conn, CORE_TERMS)
        for row in AUTHORITY_SOURCES:
            conn.execute(INSERT_AUTHORITY_SQL, row)
        conn.execute(
            "INSERT OR REPLACE INTO islamic_manifest(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO islamic_manifest(key, value) VALUES (?, ?)",
            ("seed", "riba_dual_layer_v3"),
        )
        conn.commit()
        write_manifests(principle, rule)

        preview = conn.execute(
            """
            SELECT r.rule_id, r.country, r.legal_effect, r.sharia_principle_id,
                   p.rule_subject AS principle_subject, p.legal_effect AS principle_effect
            FROM islamic_rules r
            LEFT JOIN sharia_principles p ON p.sharia_principle_id = r.sharia_principle_id
            WHERE r.rule_id = ?
            """,
            (rule.rule_id,),
        ).fetchone()
        term_count = conn.execute("SELECT COUNT(*) FROM terminology").fetchone()[0]
        auth_count = conn.execute("SELECT COUNT(*) FROM authority_sources").fetchone()[0]

        print(f"Database: {DB_PATH}")
        print(f"Inserted principles={n_p} rules={n_r} terms={n_t} authorities={auth_count}")
        print(f"Manifest shared: {MANIFEST_SHARED}")
        print(f"Manifest MY: {MANIFEST_MY}")
        print("Join preview:")
        print(json.dumps(dict(preview), ensure_ascii=False, indent=2))
        print(f"terminology rows: {term_count}")
        print("Canonical:")
        print(json.dumps(rule.to_canonical_result(principle), ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
