#!/usr/bin/env python3
"""
校验 4.3：共享层原则 ↔ 国家实例双向关联完整，并能按原则 ID 反查各国实例。

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
  .venv/bin/python -m RAG.islamic_law.scripts.verify_principle_links
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
    rules_by_principle,
)
from RAG.islamic_law.scripts.insert_riba_sample import (  # noqa: E402
    FORMAL_PRINCIPLE_BY_RULE,
    FORMAL_RULE_IDS,
    PRINCIPLE_PACKS,
    build_principle_rule_index,
    load_country_rules,
    load_principle_pack,
)

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "sources" / "shared" / "principle_links"

# 至少须能反查到印尼实例的原则（4.1 + 4.2）
REQUIRED_ID_BY_PRINCIPLE: dict[str, list[str]] = {
    "SH-PRINCIPLE-RIBA-001": [
        "ID-FIN-MUI-BUNGA-2004-001",
        "ID-FIN-UU21-2008-001",
        "ID-FIN-POJK16-2022-001",
    ],
    "SH-PRINCIPLE-SUKUK-001": [
        "ID-FIN-POJK18-2015-001",
    ],
    "SH-PRINCIPLE-HALAL-HARAM-001": [
        "ID-HALAL-UU33-2014-001",
        "ID-HALAL-PP42-2024-001",
        "ID-HALAL-BPJPH-2026-001",
        "ID-HALAL-JPH-CORE-001",
    ],
}


def _json_packs_index() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in PRINCIPLE_PACKS:
        for principle in load_principle_pack(path):
            out[principle.sharia_principle_id] = list(principle.country_rule_ids)
    return out


def run_verification() -> dict:
    reset_engine()
    if not ensure_islamic_database_ready():
        raise RuntimeError("Islamic DB not ready; run insert_riba_sample first")

    rules = load_country_rules()
    expected = build_principle_rule_index(rules)
    persisted = _json_packs_index()

    checks: list[dict] = []
    failures: list[str] = []

    # 1) JSON ↔ RULE_PACKS 一致
    for pid, exp_ids in sorted(expected.items()):
        got = sorted(persisted.get(pid, []))
        ok = got == exp_ids
        checks.append(
            {
                "check": "json_equals_rules",
                "sharia_principle_id": pid,
                "expected": len(exp_ids),
                "got": len(got),
                "pass": ok,
            }
        )
        if not ok:
            failures.append(f"JSON mismatch {pid}: expected {len(exp_ids)} got {len(got)}")

    for pid in sorted(set(persisted) - set(expected)):
        if persisted[pid]:
            failures.append(f"JSON has orphan links on {pid}: {persisted[pid][:5]}")

    # 2) 每条 formal 正向挂接存在于原则反向列表
    for rid in FORMAL_RULE_IDS:
        pid = FORMAL_PRINCIPLE_BY_RULE[rid]
        ok = rid in expected.get(pid, [])
        checks.append(
            {
                "check": "formal_in_principle",
                "rule_id": rid,
                "sharia_principle_id": pid,
                "pass": ok,
            }
        )
        if not ok:
            failures.append(f"formal {rid} missing from {pid}.country_rule_ids")

    # 3) 原则 ID 反查 API：含 MY/ID 分组，且关键印尼 formal 可命中
    api_rows: list[dict] = []
    for pid, required_ids in REQUIRED_ID_BY_PRINCIPLE.items():
        payload = json.loads(rules_by_principle(pid))
        ok_api = bool(payload.get("success"))
        by_country = payload.get("by_country") or {}
        data_ids = {item.get("rule_id") for item in (payload.get("data") or [])}
        missing_req = [rid for rid in required_ids if rid not in data_ids]
        ok = ok_api and not missing_req and "ID" in by_country
        row = {
            "check": "rules_by_principle",
            "sharia_principle_id": pid,
            "total_count": payload.get("total_count"),
            "by_country": {k: len(v) for k, v in by_country.items()},
            "missing_required_id": missing_req,
            "pass": ok,
        }
        api_rows.append(row)
        checks.append(row)
        if not ok:
            failures.append(f"rules_by_principle({pid}) failed: {row}")

    # 4) 每条带 sharia_principle_id 的 ID 规则都能从原则反查到
    id_rules = [r for r in rules if r.country == "ID" and r.sharia_principle_id]
    for rule in id_rules:
        ok = rule.rule_id in expected.get(rule.sharia_principle_id, [])
        if not ok:
            failures.append(
                f"ID rule {rule.rule_id} not reverse-linked under {rule.sharia_principle_id}"
            )
        checks.append(
            {
                "check": "id_rule_reverse",
                "rule_id": rule.rule_id,
                "sharia_principle_id": rule.sharia_principle_id,
                "pass": ok,
            }
        )

    report = {
        "verified_at": date.today().isoformat(),
        "step": "4.3",
        "all_pass": not failures,
        "principle_counts": {pid: len(ids) for pid, ids in sorted(expected.items())},
        "id_rule_count": len(id_rules),
        "formal_count": len(FORMAL_RULE_IDS),
        "api_samples": api_rows,
        "failure_count": len(failures),
        "failures": failures,
        "checks_pass": sum(1 for c in checks if c.get("pass")),
        "checks_total": len(checks),
    }
    return report


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = run_verification()
    (OUT_DIR / "REPORT.step4_3.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 4.3 共享层挂回校验",
        "",
        f"- verified_at: `{report['verified_at']}`",
        f"- all_pass: **{'PASS' if report['all_pass'] else 'FAIL'}**",
        f"- checks: {report['checks_pass']}/{report['checks_total']}",
        f"- ID rules with principle: {report['id_rule_count']}",
        "",
        "## 原则 → 实例数",
        "",
        "| principle | count |",
        "| --- | ---: |",
    ]
    for pid, n in report["principle_counts"].items():
        lines.append(f"| `{pid}` | {n} |")
    lines += ["", "## 反查 API 抽样（须含印尼）", ""]
    for row in report["api_samples"]:
        status = "PASS" if row["pass"] else "FAIL"
        lines.append(
            f"- `{row['sharia_principle_id']}` {status} "
            f"total={row['total_count']} by_country={row['by_country']}"
        )
    if report["failures"]:
        lines += ["", "## Failures", ""]
        lines.extend(f"- {x}" for x in report["failures"])
    (OUT_DIR / "REPORT.step4_3.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for row in report["api_samples"]:
        mark = "PASS" if row["pass"] else "FAIL"
        print(
            f"{mark}  {row['sharia_principle_id']}  "
            f"total={row['total_count']}  by_country={row['by_country']}"
        )
    print()
    print(("ALL_PASS" if report["all_pass"] else "FAILED") + f"  {report['checks_pass']}/{report['checks_total']}")
    print(f"wrote {OUT_DIR / 'REPORT.step4_3.md'}")
    if not report["all_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
