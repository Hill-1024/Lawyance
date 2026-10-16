#!/usr/bin/env python3
"""检查法律向量索引健康度、点数与 manifest。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check Lawver legal vector index health")
    parser.add_argument("--sample", type=int, default=5, help="payload 抽样条数")
    args = parser.parse_args()

    from vector_store.ingest import check_index

    report = check_index(sample_size=args.sample)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    checks = report.get("checks") or {}
    qdrant = report.get("qdrant") or {}
    if report.get("bm25_count", 0) <= 0 and not qdrant.get("ok"):
        return 1
    if checks.get("payload_sample_ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
