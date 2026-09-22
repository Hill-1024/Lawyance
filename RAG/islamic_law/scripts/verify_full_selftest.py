#!/usr/bin/env python3
"""
5.1 全量自测：对全部正式条目（MY+ID）分别用 exact / semantic / link_search 验证命中。

要求：
- 每条至少被 2 种检索方式命中
- 中文 query 能命中（跨语言）
- 另测英文与本地语（MY=马来语关键词；ID=印尼语关键词）一轮
- 不修改 tools/__init__.py / mcps.py

用法（仓库根目录，可独立运行）：
  .venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
  .venv/bin/python -m RAG.islamic_law.scripts.verify_full_selftest
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.islamic_law import (  # noqa: E402
    ensure_islamic_database_ready,
    exact_search,
    link_search,
    reset_engine,
    semantic_search,
)
from RAG.islamic_law.scripts.insert_riba_sample import (  # noqa: E402
    FORMAL_PRINCIPLE_BY_RULE,
    FORMAL_RULE_IDS,
    load_country_rules,
)

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "sources" / "shared" / "verify_full_selftest"
TOP_N = 15
MIN_METHODS = 2

# 每条 formal：zh / en / local 关键词（local：MY≈ms，ID≈id）
# exact 另用 law_name + article_key（见脚本逻辑）
QUERY_MATRIX: dict[str, dict[str, list[str]]] = {
    "MY-RIBA-IFSA-2013-001": {
        "zh": ["马来西亚禁止 riba 利息 IFSA", "马来西亚伊斯兰金融法禁止利息"],
        "en": ["Malaysia IFSA riba prohibition formal", "Islamic Financial Services Act Shariah compliance riba"],
        "local": ["Malaysia larangan riba IFSA", "Akta Perkhidmatan Kewangan Islam riba"],
    },
    "MY-SUKUK-BNM-SAC-001": {
        "zh": ["马来西亚 sukuk 伊斯兰债券 SAC", "BNM SAC sukuk 正式条目"],
        "en": ["Malaysia BNM SAC sukuk formal", "sukuk ijarah murabahah resolution"],
        "local": ["Malaysia sukuk resolusi SAC", "bon Islam sukuk BNM"],
    },
    "MY-TAKAFUL-BNM-SAC-001": {
        "zh": ["马来西亚 takaful 伊斯兰保险", "BNM SAC takaful tabarru"],
        "en": ["Malaysia takaful BNM SAC formal", "takaful wakalah tabarru surplus"],
        "local": ["Malaysia takaful insurans Islam", "tabarru wakalah takaful SAC"],
    },
    "MY-IFSA-2013-GOV-S28-29-001": {
        "zh": ["IFSA 沙里亚合规义务 section 28", "遵从 SAC 裁决视为符合 Shariah"],
        "en": ["IFSA section 28 Shariah compliance duty", "IFSA s.29 Bank Shariah standards"],
        "local": ["IFSA pematuhan Syariah seksyen 28", "kepatuhan Shariah IFSA s.28"],
    },
    "MY-IFSA-2013-GOV-S30-38-001": {
        "zh": ["IFSA 沙里亚委员会设立", "沙里亚合规审计 section 37 38"],
        "en": ["IFSA Shariah committee sections 30-38", "fit and proper Shariah committee"],
        "local": ["Jawatankuasa Syariah IFSA", "komite Syariah seksyen 30"],
    },
    "MY-BNM-SGP-2019-FORMAL-001": {
        "zh": ["BNM 沙里亚治理政策文件 SGP 2019", "沙里亚风险管理审查审计"],
        "en": ["Shariah Governance Policy Document 2019", "BNM SGP 2019 formal"],
        "local": ["Dokumen Polisi Tadbir Urus Syariah 2019", "SGP BNM tadbir urus Syariah"],
    },
    "MY-HALAL-ACT730-FORMAL-001": {
        "zh": ["马来西亚 halal 法定定义", "Trade Descriptions Act 730 JAKIM"],
        "en": ["Malaysia Trade Descriptions Act halal formal", "P.U.(A) 430 halal definition"],
        "local": ["Akta Perihal Dagangan halal", "takrif halal Malaysia JAKIM"],
    },
    "MY-HALAL-MS1500-FORMAL-001": {
        "zh": ["MS 1500 halal 食品标准", "马来西亚 halal 认证程序手册"],
        "en": ["MS 1500 halal food standard formal", "MPPHM Halal Malaysia portal"],
        "local": ["MS 1500 piawaian makanan halal", "manual prosedur pensijilan halal"],
    },
    "ID-HALAL-UU33-2014-001": {
        "zh": ["印尼 UU 33/2014 清真产品保障法", "BPJPH 强制清真认证母法"],
        "en": ["Indonesia UU 33/2014 Jaminan Produk Halal", "mandatory Sertifikat Halal Pasal 4"],
        "local": ["Undang-Undang 33 2014 Jaminan Produk Halal", "wajib bersertifikat halal Pasal 4"],
    },
    "ID-HALAL-PP42-2024-001": {
        "zh": ["印尼 PP 42/2024 过渡期 2026-10-17", "印尼 halal 分阶段强制时间表"],
        "en": ["Indonesia PP 42/2024 Pasal 160 transition", "Government Regulation 42 2024 halal"],
        "local": ["Peraturan Pemerintah 42 2024 Pasal 160", "batas transisi 17 Oktober 2026 UMK"],
    },
    "ID-HALAL-BPJPH-2026-001": {
        "zh": ["2026-10-18 全面强制 官方不再延期", "印尼小微进口产品清真强制"],
        "en": ["BPJPH wajib halal 18 Oktober 2026", "Indonesia mandatory halal October 2026"],
        "local": ["wajib halal mulai 18 Oktober 2026", "BPJPH pengumuman sertifikat halal"],
    },
    "ID-HALAL-JPH-CORE-001": {
        "zh": ["印尼 halal 核心制度 UU PP BPJPH", "Jaminan Produk Halal 全面强制"],
        "en": ["Indonesia halal core framework formal", "UU PP BPJPH mandatory 2026-10-18"],
        "local": ["kerangka inti Jaminan Produk Halal", "UU 33 PP 42 BPJPH wajib halal"],
    },
    "ID-FIN-MUI-BUNGA-2004-001": {
        "zh": ["印尼 Fatwa MUI 1/2004 利息 riba haram", "DSN-MUI 禁息法特瓦"],
        "en": ["Fatwa MUI 1/2004 bunga interest riba", "Indonesia fatwa interest prohibited"],
        "local": ["Fatwa MUI Nomor 1 Tahun 2004 tentang Bunga", "bunga bank haram riba nasi'ah"],
    },
    "ID-FIN-UU21-2008-001": {
        "zh": ["印尼 UU 21/2008 伊斯兰银行法", "Bank Umum Syariah Prinsip Syariah DPS"],
        "en": ["Indonesia UU 21/2008 Perbankan Syariah", "Islamic banking parent law spin-off UUS"],
        "local": ["Undang-Undang 21 2008 Perbankan Syariah", "Pemisahan UUS menjadi Bank Umum Syariah"],
    },
    "ID-FIN-POJK16-2022-001": {
        "zh": ["印尼 POJK 16/2022 伊斯兰商业银行", "POJK.03 废止 PBI 11/3/2009"],
        "en": ["POJK 16/2022 Bank Umum Syariah formal", "OJK Islamic commercial bank regulation"],
        "local": ["POJK 16 POJK.03 2022 Bank Umum Syariah", "mencabut PBI 11/3/PBI/2009"],
    },
    "ID-FIN-POJK18-2015-001": {
        "zh": ["印尼 POJK 18/2015 Sukuk 发行", "Sukuk undivided share 底层资产"],
        "en": ["POJK 18/2015 Penerbitan Persyaratan Sukuk", "Indonesia sukuk issuance DSN-MUI"],
        "local": ["POJK 18 POJK.04 2015 penerbitan sukuk", "aset mendasari sukuk prinsip syariah"],
    },
}


def _rank_of(rule_id: str, items: list[dict]) -> int | None:
    for i, item in enumerate(items, 1):
        rid = item.get("rule_id") or item.get("source_id")
        if rid == rule_id:
            return i
    return None


def _link_items(payload: dict) -> list[dict]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    refs = payload.get("references") or []
    return [x for x in refs if isinstance(x, dict)]


def _test_exact(rule) -> dict:
    # 优先用显式 article_key，避免 Formal 条目被抽成 Section 数字
    article = rule.article_key or rule.article_number
    payload = json.loads(exact_search(rule.law_name, article))
    hit_id = None
    if payload.get("success") and isinstance(payload.get("data"), dict):
        hit_id = payload["data"].get("rule_id")
    ok = hit_id == rule.rule_id
    return {
        "method": "exact",
        "pass": ok,
        "query": {"law_name": rule.law_name, "article": article},
        "hit_rule_id": hit_id,
        "message": payload.get("message"),
    }


def _test_semantic(rule_id: str, queries: list[str]) -> dict:
    best = None
    attempts = []
    for query in queries:
        payload = json.loads(semantic_search(query, TOP_N))
        items = [x for x in (payload.get("data") or []) if isinstance(x, dict)]
        rank = _rank_of(rule_id, items)
        attempts.append({"query": query, "rank": rank, "returned": len(items)})
        if rank is not None and (best is None or rank < best["rank"]):
            best = {"query": query, "rank": rank}
    return {
        "method": "semantic",
        "pass": best is not None,
        "best": best,
        "attempts": attempts,
    }


def _test_link(rule_id: str, queries: list[str]) -> dict:
    best = None
    attempts = []
    for query in queries:
        payload = json.loads(link_search(query, TOP_N))
        items = _link_items(payload)
        rank = _rank_of(rule_id, items)
        attempts.append({"query": query, "rank": rank, "returned": len(items)})
        if rank is not None and (best is None or rank < best["rank"]):
            best = {"query": query, "rank": rank}
    return {
        "method": "link",
        "pass": best is not None,
        "best": best,
        "attempts": attempts,
    }


def run_verification() -> dict:
    reset_engine()
    if not ensure_islamic_database_ready():
        raise RuntimeError("Islamic DB not ready; run insert_riba_sample first")

    by_id = {r.rule_id: r for r in load_country_rules()}
    rows: list[dict] = []

    for rid in FORMAL_RULE_IDS:
        if rid not in QUERY_MATRIX:
            raise ValueError(f"QUERY_MATRIX missing {rid}")
        rule = by_id[rid]
        langs = QUERY_MATRIX[rid]
        # 跨语言：中文语义必须命中；英文/本地语各测一轮
        zh_sem = _test_semantic(rid, langs["zh"])
        en_sem = _test_semantic(rid, langs["en"])
        local_sem = _test_semantic(rid, langs["local"])
        # 三种检索方式（semantic 合并三语命中；link 用中英本地各一条优先）
        exact = _test_exact(rule)
        semantic = {
            "method": "semantic",
            "pass": zh_sem["pass"] or en_sem["pass"] or local_sem["pass"],
            "zh": zh_sem,
            "en": en_sem,
            "local": local_sem,
        }
        link_queries = [
            langs["zh"][0],
            langs["en"][0],
            langs["local"][0],
        ]
        link = _test_link(rid, link_queries)

        methods_hit = [
            m
            for m, block in (("exact", exact), ("semantic", semantic), ("link", link))
            if block["pass"]
        ]
        zh_ok = bool(zh_sem["pass"])
        ok = len(methods_hit) >= MIN_METHODS and zh_ok
        rows.append(
            {
                "rule_id": rid,
                "country": rule.country,
                "sharia_principle_id": FORMAL_PRINCIPLE_BY_RULE[rid],
                "methods_hit": methods_hit,
                "methods_hit_count": len(methods_hit),
                "zh_hit": zh_ok,
                "pass": ok,
                "exact": exact,
                "semantic": semantic,
                "link": link,
            }
        )

    pass_count = sum(1 for r in rows if r["pass"])
    zh_pass = sum(1 for r in rows if r["zh_hit"])
    return {
        "verified_at": date.today().isoformat(),
        "step": "5.1",
        "scope": "MY+ID formal only",
        "top_n": TOP_N,
        "min_methods": MIN_METHODS,
        "criterion": (
            "每条正式条目至少被 exact/semantic/link 中的 2 种命中；"
            "且中文 semantic query 必须命中（跨语言）"
        ),
        "formal_count": len(FORMAL_RULE_IDS),
        "pass_count": pass_count,
        "zh_pass_count": zh_pass,
        "all_pass": pass_count == len(FORMAL_RULE_IDS),
        "results": rows,
    }


def write_report(report: dict) -> tuple[Path, Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "REPORT.step5_1.json"
    md_path = OUT_DIR / "REPORT.step5_1.md"
    prov_path = OUT_DIR / "provenance.step5_1.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 5.1 全量自测报告",
        "",
        f"- verified_at: `{report['verified_at']}`",
        f"- scope: `{report['scope']}`",
        f"- all_pass: **{'PASS' if report['all_pass'] else 'FAIL'}**",
        f"- formal: {report['pass_count']}/{report['formal_count']}",
        f"- 中文命中: {report['zh_pass_count']}/{report['formal_count']}",
        f"- 标准: {report['criterion']}",
        "",
        "| rule_id | country | methods | zh | pass |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["results"]:
        lines.append(
            f"| `{row['rule_id']}` | {row['country']} | "
            f"`{'+'.join(row['methods_hit']) or '—'}` | "
            f"{'Y' if row['zh_hit'] else 'N'} | "
            f"{'PASS' if row['pass'] else 'FAIL'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    provenance = {
        "collected_at": report["verified_at"],
        "step": "5.1",
        "topic": "full_selftest_exact_semantic_link",
        "scope": "MY+ID",
        "all_pass": report["all_pass"],
        "pass_count": report["pass_count"],
        "formal_count": report["formal_count"],
        "zh_pass_count": report["zh_pass_count"],
        "script": "scripts/verify_full_selftest.py",
        "note": "不修改 tools/__init__.py / mcps.py；仅准备管辖库自测",
    }
    prov_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return json_path, md_path, prov_path


def main() -> int:
    report = run_verification()
    json_path, md_path, _ = write_report(report)
    for row in report["results"]:
        mark = "PASS" if row["pass"] else "FAIL"
        print(
            f"{mark}  {row['rule_id']}  methods={row['methods_hit']}  "
            f"zh={'Y' if row['zh_hit'] else 'N'}"
        )
    print()
    print(
        ("ALL_PASS" if report["all_pass"] else "HAS_FAIL"),
        f"{report['pass_count']}/{report['formal_count']}",
        f"zh={report['zh_pass_count']}/{report['formal_count']}",
    )
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
