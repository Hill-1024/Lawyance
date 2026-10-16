#!/usr/bin/env python3
"""按 content_hash / embedding_version 增量更新法律向量索引。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Incrementally update Lawver legal vector index")
    parser.add_argument("--china-only", action="store_true")
    parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="只更新指定 source_id（可重复）",
    )
    args = parser.parse_args()

    from vector_store.ingest import update_index

    stats = update_index(
        changed_source_ids=args.source_id or None,
        include_asean=not args.china_only,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
