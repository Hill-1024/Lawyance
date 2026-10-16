#!/usr/bin/env python3
"""从零构建法律向量库（Qdrant + BM25）与 index manifest。"""

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
    parser = argparse.ArgumentParser(description="Build Lawver legal vector index")
    parser.add_argument("--china-only", action="store_true", help="仅索引中国法")
    parser.add_argument("--limit-files", type=int, default=None, help="限制中国法源文件数（调试）")
    parser.add_argument("--recreate", action="store_true", help="重建 Qdrant collection")
    parser.add_argument("--bm25-only", action="store_true", help="只写 BM25，不写 Qdrant")
    parser.add_argument("--qdrant-only", action="store_true", help="只写 Qdrant，不写 BM25")
    args = parser.parse_args()

    from vector_store.ingest import build_index

    stats = build_index(
        include_asean=not args.china_only,
        limit_files=args.limit_files,
        recreate_collection=args.recreate,
        skip_qdrant=args.bm25_only,
        skip_bm25=args.qdrant_only,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
