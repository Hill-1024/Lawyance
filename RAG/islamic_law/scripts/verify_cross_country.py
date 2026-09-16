#!/usr/bin/env python3
"""
跨国对比验证（4.4）：同一共享原则下须能看到 ≥2 个国家的转化实例。

核心场景：「禁止 riba」→ SH-PRINCIPLE-RIBA-001 同时出现马来西亚与印尼版本。
手段：rules_by_principle（按原则 ID）+ semantic_search / link_search。

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
  .venv/bin/python -m RAG.islamic_law.scripts.verify_cross_country
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
    link_search,
    reset_engine,
    rules_by_principle,
    semantic_search,
)

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "sources" / "shared" / "verify_cross_country"
MIN_COUNTRIES = 2
TOP_N = 20

# 转化层国家码（排除共享层 XX）
COUNTRY_LAYER = frozenset({"MY", "ID", "BN", "SG", "PH", "TH", "VN", "LA", "KH", "MM", "TL"})

# 原则级：按 sharia_principle_id 反查，须 ≥2 国（已有多国实例的原则）
PRINCIPLE_CASES: list[dict] = [
    {
        "sharia_principle_id": "SH-PRINCIPLE-RIBA-001",
        "label": "禁止 riba",
        "required_countries": ["MY", "ID"],
        "required_formals": {
            "MY": ["MY-RIBA-IFSA-2013-001"],
            "ID": ["ID-FIN-MUI-BUNGA-2004-001", "ID-FIN-UU21-2008-001"],
        },
    },
    {
        "sharia_principle_id": "SH-PRINCIPLE-SUKUK-001",
        "label": "sukuk",
        "required_countries": ["MY", "ID"],
        "required_formals": {
            "MY": ["MY-SUKUK-BNM-SAC-001"],
            "ID": ["ID-FIN-POJK18-2015-001"],
        },
    },
    {
        "sharia_principle_id": "SH-PRINCIPLE-HALAL-HARAM-001",
        "label": "halal/haram",
        "required_countries": ["MY", "ID"],
        "required_formals": {
            "MY": ["MY-HALAL-ACT730-FORMAL-001"],
            "ID": ["ID-HALAL-UU33-2014-001", "ID-HALAL-JPH-CORE-001"],
        },
    },
]

# 检索级：自然语言 / link 须在 Top-N 同时命中 ≥2 国转化实例
SEARCH_CASES: list[dict] = [
    {
        "mode": "semantic",
        "query": "禁止 riba",
        "required_countries": ["MY", "ID"],
        "required_rule_ids": ["MY-RIBA-IFSA-2013-001", "ID-FIN-MUI-BUNGA-2004-001"],
        "principle_hint": "SH-PRINCIPLE-RIBA-001",
    },
    {
        "mode": "semantic",
        "query": "riba 利息 马来西亚 印尼",
        "required_countries": ["MY", "ID"],
        "required_rule_ids": ["MY-RIBA-IFSA-2013-001"],
        "principle_hint": "SH-PRINCIPLE-RIBA-001",
    },
    {
        "mode": "link",
        "query": "禁止 riba",
        "required_countries": ["MY", "ID"],
        "required_rule_ids": ["MY-RIBA-IFSA-2013-001", "ID-FIN-MUI-BUNGA-2004-001"],
        "principle_hint": "SH-PRINCIPLE-RIBA-001",
    },
    {
        "mode": "link",
        "query": "SH-PRINCIPLE-RIBA-001",
        "required_countries": ["MY", "ID"],
        "required_rule_ids": [],
        "principle_hint": "SH-PRINCIPLE-RIBA-001",
    },
]


def _country_codes(items: list[dict]) -> list[str]:
    codes = {
        str(item.get("country") or "").upper()
        for item in items
        if str(item.get("country") or "").upper() in COUNTRY_LAYER
    }
    return sorted(codes)


def _items_from_link(payload: dict) -> list[dict]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    refs = payload.get("references") or []
    return [x for x in refs if isinstance(x, dict)]


def _check_principle(case: dict) -> dict:
    pid = case["sharia_principle_id"]
    payload = json.loads(rules_by_principle(pid, limit=200))
    by_country = payload.get("by_country") or {}
    country_counts = {
        code: len(rows)
        for code, rows in by_country.items()
        if code in COUNTRY_LAYER and rows
    }
    countries = sorted(country_counts)
    data_ids = {item.get("rule_id") for item in (payload.get("data") or [])}

    missing_countries = [c for c in case["required_countries"] if c not in country_counts]
    missing_formals: dict[str, list[str]] = {}
    for code, formals in (case.get("required_formals") or {}).items():
        miss = [rid for rid in formals if rid not in data_ids]
        if miss:
            missing_formals[code] = miss

    ok = (
        bool(payload.get("success"))
        and len(countries) >= MIN_COUNTRIES
        and not missing_countries
        and not missing_formals
    )
    return {
        "check": "rules_by_principle",
        "label": case["label"],
        "sharia_principle_id": pid,
        "countries": countries,
        "country_counts": country_counts,
        "total_count": payload.get("total_count"),
        "missing_countries": missing_countries,
        "missing_formals": missing_formals,
        "pass": ok,
    }


def _check_search(case: dict) -> dict:
    query = case["query"]
    mode = case["mode"]
    if mode == "semantic":
        payload = json.loads(semantic_search(query, TOP_N))
        items = [x for x in (payload.get("data") or []) if isinstance(x, dict)]
    elif mode == "link":
        payload = json.loads(link_search(query, TOP_N))
        items = _items_from_link(payload)
    else:
        raise ValueError(f"unknown mode {mode}")

    # 仅计转化层国家（MY/ID…）；共享层 XX 不计入「国家数」
    countries = _country_codes(items)
    ids = {x.get("rule_id") for x in items}
    missing_countries = [c for c in case["required_countries"] if c not in countries]
    missing_rules = [rid for rid in (case.get("required_rule_ids") or []) if rid not in ids]
    samples = {
        code: [x.get("rule_id") for x in items if x.get("country") == code][:5]
        for code in countries
    }

    ok = (
        bool(payload.get("success"))
        and len(countries) >= MIN_COUNTRIES
        and not missing_countries
        and not missing_rules
    )
    return {
        "check": mode,
        "query": query,
        "countries": countries,
        "samples_by_country": samples,
        "missing_countries": missing_countries,
        "missing_rules": missing_rules,
        "returned_count": len(items),
        "principle_hint": case.get("principle_hint") or "",
        "pass": ok,
    }


def run_verification() -> dict:
    reset_engine()
    if not ensure_islamic_database_ready():
        raise RuntimeError("Islamic DB not ready; run insert_riba_sample first")

    principle_rows = [_check_principle(case) for case in PRINCIPLE_CASES]
    search_rows = [_check_search(case) for case in SEARCH_CASES]
    all_rows = principle_rows + search_rows
    failures = [
        row
        for row in all_rows
        if not row.get("pass")
    ]

    # 核心场景摘要：禁止 riba
    riba_principle = next(
        r for r in principle_rows if r["sharia_principle_id"] == "SH-PRINCIPLE-RIBA-001"
    )
    riba_semantic = next(
        r for r in search_rows if r["check"] == "semantic" and r["query"] == "禁止 riba"
    )
    riba_link = next(
        r for r in search_rows if r["check"] == "link" and r["query"] == "禁止 riba"
    )

    return {
        "verified_at": date.today().isoformat(),
        "step": "4.4",
        "min_countries": MIN_COUNTRIES,
        "top_n": TOP_N,
        "all_pass": not failures,
        "core_scenario": {
            "query": "禁止 riba",
            "principle": "SH-PRINCIPLE-RIBA-001",
            "rules_by_principle_countries": riba_principle["countries"],
            "semantic_countries": riba_semantic["countries"],
            "link_countries": riba_link["countries"],
            "pass": riba_principle["pass"] and riba_semantic["pass"] and riba_link["pass"],
        },
        "principle_checks": principle_rows,
        "search_checks": search_rows,
        "checks_pass": sum(1 for r in all_rows if r.get("pass")),
        "checks_total": len(all_rows),
        "failures": failures,
    }


def _write_report(report: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "REPORT.step4_4.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    core = report["core_scenario"]
    lines = [
        "# 4.4 跨国对比验证",
        "",
        f"- verified_at: `{report['verified_at']}`",
        f"- all_pass: **{'PASS' if report['all_pass'] else 'FAIL'}**",
        f"- checks: {report['checks_pass']}/{report['checks_total']}",
        f"- 要求：同一原则下转化实例国家数 ≥ {report['min_countries']}",
        "",
        "## 核心场景：禁止 riba",
        "",
        f"- principle: `{core['principle']}`",
        f"- `rules_by_principle` countries: `{core['rules_by_principle_countries']}`",
        f"- `semantic_search(\"禁止 riba\")` countries: `{core['semantic_countries']}`",
        f"- `link_search(\"禁止 riba\")` countries: `{core['link_countries']}`",
        f"- core_pass: **{'PASS' if core['pass'] else 'FAIL'}**",
        "",
        "## 按原则 ID 反查",
        "",
        "| principle | label | countries | counts | pass |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["principle_checks"]:
        lines.append(
            f"| `{row['sharia_principle_id']}` | {row['label']} | "
            f"`{row['countries']}` | `{row['country_counts']}` | "
            f"{'PASS' if row['pass'] else 'FAIL'} |"
        )
    lines += ["", "## semantic / link 检索", "", "| mode | query | countries | pass |", "| --- | --- | --- | --- |"]
    for row in report["search_checks"]:
        lines.append(
            f"| {row['check']} | `{row['query']}` | `{row['countries']}` | "
            f"{'PASS' if row['pass'] else 'FAIL'} |"
        )
    if report["failures"]:
        lines += ["", "## Failures", ""]
        for row in report["failures"]:
            lines.append(f"- `{json.dumps(row, ensure_ascii=False)}`")
    (OUT_DIR / "REPORT.step4_4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    provenance = {
        "collected_at": report["verified_at"],
        "step": "4.4",
        "topic": "cross_country_comparison",
        "requirement": "同一原则下 ≥2 个国家转化实例；禁止 riba 须同时见 MY + ID",
        "core_scenario": report["core_scenario"],
        "all_pass": report["all_pass"],
        "scripts": ["scripts/verify_cross_country.py"],
        "report": ["REPORT.step4_4.md", "REPORT.step4_4.json"],
    }
    (OUT_DIR / "provenance.step4_4.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    report = run_verification()
    _write_report(report)

    core = report["core_scenario"]
    print(
        f"CORE  禁止 riba  "
        f"principle={core['rules_by_principle_countries']}  "
        f"semantic={core['semantic_countries']}  "
        f"link={core['link_countries']}  "
        f"{'PASS' if core['pass'] else 'FAIL'}"
    )
    for row in report["principle_checks"]:
        print(
            f"{'PASS' if row['pass'] else 'FAIL'}  principle  "
            f"{row['sharia_principle_id']}  countries={row['countries']}  "
            f"counts={row['country_counts']}"
        )
    for row in report["search_checks"]:
        print(
            f"{'PASS' if row['pass'] else 'FAIL'}  {row['check']}  "
            f"q={row['query']!r}  countries={row['countries']}"
        )
    print()
    print(
        ("ALL_PASS" if report["all_pass"] else "FAILED")
        + f"  {report['checks_pass']}/{report['checks_total']}"
    )
    print(f"wrote {OUT_DIR / 'REPORT.step4_4.md'}")
    if not report["all_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
