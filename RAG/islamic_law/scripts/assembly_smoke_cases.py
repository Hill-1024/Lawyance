#!/usr/bin/env python3
"""
5.2 总装接口冒烟用例（可独立运行；不依赖 tools/mcps）。

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.assembly_smoke_cases

说明见 RAG/islamic_law/INTERFACE.md
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.islamic_law import (  # noqa: E402
    ensure_islamic_database_ready,
    exact_search,
    link_search,
    reset_engine,
    rules_by_principle,
    semantic_search,
)

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "sources" / "shared" / "assembly_interface"


@dataclass
class CaseResult:
    case_id: str
    title: str
    passed: bool
    detail: str


def _countries(items: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("country") or "").upper()
        for item in items
        if str(item.get("country") or "").upper() in {"MY", "ID"}
    }


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("rule_id") or "") for item in items if item.get("rule_id")}


def case_01_semantic_riba_zh() -> CaseResult:
    """中文「禁止 riba」须同时看到马来西亚与印尼转化实例。"""
    payload = json.loads(semantic_search("禁止 riba", 15))
    items = [x for x in (payload.get("data") or []) if isinstance(x, dict)]
    countries = _countries(items)
    ok = bool(payload.get("success")) and {"MY", "ID"}.issubset(countries)
    return CaseResult(
        "01",
        "semantic_search 中文禁止 riba → MY+ID",
        ok,
        f"countries={sorted(countries)} returned={len(items)}",
    )


def case_02_exact_my_riba_formal() -> CaseResult:
    """exact：法名 + article_key 命中马来西亚 riba 正式条目。"""
    law = "Islamic Financial Services Act 2013"
    article_key = "MY-RIBA-FORMAL"
    payload = json.loads(exact_search(law, article_key))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rid = data.get("rule_id")
    ok = bool(payload.get("success")) and rid == "MY-RIBA-IFSA-2013-001"
    return CaseResult(
        "02",
        "exact_search MY riba formal",
        ok,
        f"hit={rid!r} article_key={article_key}",
    )


def case_03_link_riba() -> CaseResult:
    """link_search「禁止 riba」返回可引用 data，且含 MY+ID。"""
    payload = json.loads(link_search("禁止 riba", 15))
    items = [x for x in (payload.get("data") or []) if isinstance(x, dict)]
    countries = _countries(items)
    refs = payload.get("references") or []
    ok = (
        bool(payload.get("success"))
        and {"MY", "ID"}.issubset(countries)
        and isinstance(refs, list)
        and len(refs) >= 1
    )
    return CaseResult(
        "03",
        "link_search 禁止 riba → MY+ID + references",
        ok,
        f"countries={sorted(countries)} refs={len(refs)}",
    )


def case_04_principle_riba_id() -> CaseResult:
    """按原则 ID 反查印尼 riba 转化（须含 formal）。"""
    payload = json.loads(rules_by_principle("SH-PRINCIPLE-RIBA-001", country="ID"))
    items = [x for x in (payload.get("data") or []) if isinstance(x, dict)]
    ids = _ids(items)
    need = {"ID-FIN-MUI-BUNGA-2004-001", "ID-FIN-UU21-2008-001"}
    ok = bool(payload.get("success")) and need.issubset(ids)
    return CaseResult(
        "04",
        "rules_by_principle RIBA country=ID",
        ok,
        f"total={payload.get('total_count')} has={sorted(need & ids)}",
    )


def case_05_semantic_id_halal_zh() -> CaseResult:
    """中文跨语言：2026-10-18 全面强制 → 印尼 halal formal。"""
    payload = json.loads(semantic_search("2026-10-18 全面强制 官方不再延期", 10))
    items = [x for x in (payload.get("data") or []) if isinstance(x, dict)]
    ids = _ids(items)
    target = {"ID-HALAL-BPJPH-2026-001", "ID-HALAL-JPH-CORE-001", "ID-HALAL-PP42-2024-001"}
    hit = ids & target
    ok = bool(payload.get("success")) and bool(hit)
    return CaseResult(
        "05",
        "semantic_search 中文 2026-10-18 清真强制",
        ok,
        f"hit={sorted(hit)}",
    )


CASES: list[Callable[[], CaseResult]] = [
    case_01_semantic_riba_zh,
    case_02_exact_my_riba_formal,
    case_03_link_riba,
    case_04_principle_riba_id,
    case_05_semantic_id_halal_zh,
]


def main() -> int:
    reset_engine()
    meta = ensure_islamic_database_ready()
    print(f"db ready: mode={meta.get('mode')} path={meta.get('db_path')}")
    print()

    results = [fn() for fn in CASES]
    for row in results:
        mark = "PASS" if row.passed else "FAIL"
        print(f"{mark}  [{row.case_id}] {row.title}  ({row.detail})")

    passed = sum(1 for r in results if r.passed)
    all_pass = passed == len(results)
    print()
    print(("ALL_PASS" if all_pass else "HAS_FAIL") + f"  {passed}/{len(results)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "verified_at": date.today().isoformat(),
        "step": "5.2",
        "all_pass": all_pass,
        "pass_count": passed,
        "total": len(results),
        "db": meta,
        "cases": [
            {
                "case_id": r.case_id,
                "title": r.title,
                "pass": r.passed,
                "detail": r.detail,
            }
            for r in results
        ],
        "interface_doc": "RAG/islamic_law/INTERFACE.md",
        "note": "总装冒烟；不修改 tools/__init__.py / mcps.py",
    }
    (OUT_DIR / "REPORT.step5_2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 5.2 总装接口冒烟报告",
        "",
        f"- verified_at: `{report['verified_at']}`",
        f"- all_pass: **{'PASS' if all_pass else 'FAIL'}** ({passed}/{len(results)})",
        f"- 接口文档: `INTERFACE.md`",
        "",
        "| # | 场景 | 结果 | 细节 |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.case_id} | {r.title} | {'PASS' if r.passed else 'FAIL'} | `{r.detail}` |"
        )
    (OUT_DIR / "REPORT.step5_2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_DIR / "provenance.step5_2.json").write_text(
        json.dumps(
            {
                "collected_at": report["verified_at"],
                "step": "5.2",
                "topic": "assembly_interface_smoke",
                "all_pass": all_pass,
                "docs": ["INTERFACE.md"],
                "script": "scripts/assembly_smoke_cases.py",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_DIR / 'REPORT.step5_2.md'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
