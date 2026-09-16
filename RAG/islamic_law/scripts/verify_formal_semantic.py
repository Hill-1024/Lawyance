#!/usr/bin/env python3
"""
批量验证：对所有正式条目（MY + ID）跑 semantic_search，确认每条至少被 1 个相关 query 命中。

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
  .venv/bin/python -m RAG.islamic_law.scripts.verify_formal_semantic
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
    reset_engine,
    semantic_search,
)
from RAG.islamic_law.scripts.insert_riba_sample import (  # noqa: E402
    FORMAL_PRINCIPLE_BY_RULE,
    FORMAL_RULE_IDS,
)

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "sources" / "shared" / "verify_formal"
TOP_N = 10

# 每条正式条目的相关 query（至少 1 条须命中 Top-N）
QUERIES: dict[str, list[str]] = {
    "MY-RIBA-IFSA-2013-001": [
        "马来西亚 riba 利息",
        "IFSA 禁止利息 riba 正式",
        "Malaysia riba IFSA binding",
    ],
    "MY-SUKUK-BNM-SAC-001": [
        "马来西亚 sukuk 伊斯兰债券 SAC",
        "BNM SAC sukuk ijarah 底层资产",
        "sukuk commodity murabahah tawarruq",
    ],
    "MY-TAKAFUL-BNM-SAC-001": [
        "马来西亚 takaful 伊斯兰保险",
        "BNM SAC tabarru wakalah takaful",
        "takaful 基金分账 盈余",
    ],
    "MY-IFSA-2013-GOV-S28-29-001": [
        "IFSA 沙里亚合规义务 section 28",
        "遵从 SAC 裁决视为符合 Shariah",
        "BNM 制定沙里亚治理标准 s.29",
    ],
    "MY-IFSA-2013-GOV-S30-38-001": [
        "IFSA Shariah 委员会设立",
        "沙里亚委员会任命 适格 fit and proper",
        "沙里亚合规审计 section 37 38",
    ],
    "MY-BNM-SGP-2019-FORMAL-001": [
        "BNM 沙里亚治理政策文件 SGP 2019",
        "Shariah Governance Policy Document",
        "沙里亚风险管理 审查 审计",
    ],
    "MY-HALAL-ACT730-FORMAL-001": [
        "马来西亚 halal 法定定义 P.U.A 430",
        "Trade Descriptions Act 730 halal",
        "JAKIM halal 认证主管机关",
    ],
    "MY-HALAL-MS1500-FORMAL-001": [
        "MS 1500 halal 食品标准",
        "马来西亚 halal 认证程序手册 MPPHM",
        "halal.gov.my 认证门户",
    ],
    "ID-HALAL-UU33-2014-001": [
        "印尼 UU 33/2014 清真产品保障法",
        "Indonesia Jaminan Produk Halal Pasal 4",
        "BPJPH 强制清真认证母法",
    ],
    "ID-HALAL-PP42-2024-001": [
        "印尼 PP 42/2024 过渡期 2026-10-17",
        "Peraturan Pemerintah 42 2024 Pasal 160 UMK",
        "印尼 halal 分阶段强制时间表",
    ],
    "ID-HALAL-BPJPH-2026-001": [
        "2026-10-18 全面强制 官方不再延期",
        "BPJPH wajib halal 18 Oktober 2026",
        "印尼小微进口产品清真强制",
    ],
    "ID-HALAL-JPH-CORE-001": [
        "印尼 halal 核心制度 UU PP BPJPH",
        "Indonesia halal mandatory 2026-10-18",
        "Jaminan Produk Halal 全面强制",
    ],
    "ID-FIN-MUI-BUNGA-2004-001": [
        "印尼 Fatwa MUI 1/2004 利息 riba haram",
        "MUI bunga interest faidah 禁止",
        "DSN-MUI 禁息法特瓦",
    ],
    "ID-FIN-UU21-2008-001": [
        "印尼 UU 21/2008 伊斯兰银行法",
        "Perbankan Syariah Pasal 68 spin-off UUS",
        "Bank Umum Syariah Prinsip Syariah DPS",
    ],
    "ID-FIN-POJK16-2022-001": [
        "印尼 POJK 16/2022 伊斯兰商业银行",
        "Bank Umum Syariah OJK 监管细则",
        "POJK.03 废止 PBI 11/3/2009",
    ],
    "ID-FIN-POJK18-2015-001": [
        "印尼 POJK 18/2015 Sukuk 发行",
        "Sukuk undivided share 底层资产 DSN-MUI",
        "POJK.04 Penerbitan Persyaratan Sukuk",
    ],
}


def _rank_of(rule_id: str, data: list[dict]) -> int | None:
    for i, item in enumerate(data, 1):
        rid = item.get("rule_id") or item.get("source_id")
        if rid == rule_id:
            return i
    return None


def run_verification(top_n: int = TOP_N) -> dict:
    reset_engine()
    if not ensure_islamic_database_ready():
        raise RuntimeError("Islamic DB not ready; run insert_riba_sample first")

    results: list[dict] = []
    for rid in FORMAL_RULE_IDS:
        if rid not in QUERIES:
            raise ValueError(f"No verification queries defined for {rid}")
        hits: list[dict] = []
        best: dict | None = None
        for query in QUERIES[rid]:
            payload = json.loads(semantic_search(query, top_n))
            data = payload.get("data") or []
            rank = _rank_of(rid, data)
            hits.append(
                {
                    "query": query,
                    "success": payload.get("success"),
                    "returned": payload.get("returned_count"),
                    "rank": rank,
                    "top3": [
                        {
                            "rank": i,
                            "rule_id": item.get("rule_id") or item.get("source_id"),
                            "subject": (item.get("rule_subject") or "")[:80],
                        }
                        for i, item in enumerate(data[:3], 1)
                    ],
                }
            )
            if rank is not None and (best is None or rank < best["rank"]):
                best = {"query": query, "rank": rank}
        results.append(
            {
                "rule_id": rid,
                "sharia_principle_id": FORMAL_PRINCIPLE_BY_RULE[rid],
                "pass": best is not None,
                "best_hit": best,
                "queries": hits,
            }
        )

    pass_count = sum(1 for row in results if row["pass"])
    return {
        "collected_at": str(date.today()),
        "step": "formal-batch-verify",
        "top_n": top_n,
        "formal_count": len(FORMAL_RULE_IDS),
        "all_pass": pass_count == len(FORMAL_RULE_IDS),
        "pass_count": pass_count,
        "criterion": "每条正式条目至少被 1 个相关 query 在 semantic_search Top-N 命中",
        "results": results,
    }


def write_report(report: dict) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "provenance.latest.json"
    md_path = OUT_DIR / "REPORT.latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 3.3 批量验证报告",
        "",
        f"- 日期：{report['collected_at']}",
        f"- Top-N：{report['top_n']}",
        f"- 正式条目：{report['formal_count']}",
        f"- 结果：{'ALL PASS' if report['all_pass'] else 'HAS FAIL'}"
        f"（{report['pass_count']}/{report['formal_count']}）",
        f"- 标准：{report['criterion']}",
        "",
        "| 正式条目 | 原则 | 结果 | 最佳命中 |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["results"]:
        if row["best_hit"]:
            hit = f"#{row['best_hit']['rank']} ← `{row['best_hit']['query']}`"
        else:
            hit = "—"
        lines.append(
            f"| `{row['rule_id']}` | `{row['sharia_principle_id']}` | "
            f"{'PASS' if row['pass'] else 'FAIL'} | {hit} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    report = run_verification()
    json_path, md_path = write_report(report)
    for row in report["results"]:
        if row["pass"]:
            best = row["best_hit"]
            print(f"PASS  {row['rule_id']}  best=#{best['rank']}  q={best['query']!r}")
        else:
            print(f"FAIL  {row['rule_id']}  NO HIT in top {report['top_n']}")
    print()
    print(
        "ALL_PASS" if report["all_pass"] else "HAS_FAIL",
        f"{report['pass_count']}/{report['formal_count']}",
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
