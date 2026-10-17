#!/usr/bin/env python3
"""法律混合检索离线评测：Recall@K / MRR / nDCG；支持分通道 ablation。"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _normalize_name(value: str) -> str:
    return (
        str(value or "")
        .replace("《", "")
        .replace("》", "")
        .replace(" ", "")
        .casefold()
    )


def _hit(expected: list[list[str]], items: list[Any], k: int) -> bool:
    top = items[:k]
    for law_name, article in expected:
        want_law = _normalize_name(law_name)
        want_article = str(article or "").replace(" ", "")
        for item in top:
            got_law = _normalize_name(getattr(item, "law_name", "") or item.get("law_name", ""))
            got_article = str(
                getattr(item, "article_number", "") or item.get("article_number", "")
            ).replace(" ", "")
            if want_law and want_law in got_law and (not want_article or want_article in got_article):
                return True
    return False


def _mrr(expected: list[list[str]], items: list[Any]) -> float:
    for rank, item in enumerate(items, start=1):
        got_law = _normalize_name(getattr(item, "law_name", "") or item.get("law_name", ""))
        got_article = str(
            getattr(item, "article_number", "") or item.get("article_number", "")
        ).replace(" ", "")
        for law_name, article in expected:
            want_law = _normalize_name(law_name)
            want_article = str(article or "").replace(" ", "")
            if want_law and want_law in got_law and (not want_article or want_article in got_article):
                return 1.0 / rank
    return 0.0


def _dcg(relevances: list[float]) -> float:
    total = 0.0
    for index, rel in enumerate(relevances, start=1):
        total += (2**rel - 1) / math.log2(index + 1)
    return total


def _ndcg(expected: list[list[str]], items: list[Any], k: int) -> float:
    relevances = []
    for item in items[:k]:
        got_law = _normalize_name(getattr(item, "law_name", "") or item.get("law_name", ""))
        got_article = str(
            getattr(item, "article_number", "") or item.get("article_number", "")
        ).replace(" ", "")
        rel = 0.0
        for law_name, article in expected:
            want_law = _normalize_name(law_name)
            want_article = str(article or "").replace(" ", "")
            if want_law and want_law in got_law and (not want_article or want_article in got_article):
                rel = 1.0
                break
        relevances.append(rel)
    ideal = sorted(relevances, reverse=True)
    ideal_dcg = _dcg(ideal)
    if ideal_dcg <= 0:
        return 0.0
    return _dcg(relevances) / ideal_dcg


def _jurisdiction_leak(items: list[Any], forbidden: list[str]) -> bool:
    banned = {str(code).upper() for code in forbidden if code}
    if not banned:
        return False
    for item in items:
        got = str(getattr(item, "jurisdiction", "") or item.get("jurisdiction", "")).upper()
        if got in banned:
            return True
    return False


def _run_mode(
    mode: str,
    query: str,
    *,
    system: str,
    jurisdictions: list[str] | None,
    limit: int,
) -> list[Any]:
    """按通道模式召回。hybrid / hybrid+rerank 走统一入口；其余为 ablation。"""
    from vector_store.config import get_legal_vector_config
    from vector_store.fusion import reciprocal_rank_fusion
    from vector_store.retrieval import (
        _bm25_hits,
        _dense_hits,
        _exact_hits,
        _legacy_fuzzy_hits,
        extract_citations,
        hybrid_search,
    )
    from vector_store.reranker import rerank_chunks, reranker_available

    cfg = get_legal_vector_config()
    preferred = jurisdictions or []

    if mode in {"hybrid", "hybrid+rerank", "baseline"}:
        # baseline = 关闭向量通道时的 hybrid（仅 exact+legacy）
        if mode == "baseline":
            from unittest.mock import patch

            with patch("vector_store.retrieval.hybrid_enabled", return_value=False):
                result = hybrid_search(
                    query,
                    jurisdiction_system=system,
                    jurisdictions=jurisdictions,
                    limit=limit,
                    config=cfg,
                )
        elif mode == "hybrid+rerank":
            # 临时打开 reranker（若未配置则仍返回 hybrid）
            result = hybrid_search(
                query,
                jurisdiction_system=system,
                jurisdictions=jurisdictions,
                limit=limit,
                config=cfg,
            )
            items = result.get("items") or []
            if reranker_available(cfg) and items:
                return rerank_chunks(query, items, config=cfg)[:limit]
            return items
        else:
            result = hybrid_search(
                query,
                jurisdiction_system=system,
                jurisdictions=jurisdictions,
                limit=limit,
                config=cfg,
            )
        return result.get("items") or []

    channels: dict[str, list[Any]] = {}
    if mode == "exact":
        channels["exact"] = _exact_hits(system, query)
    elif mode == "bm25":
        channels["bm25"] = _bm25_hits(
            query, system=system, jurisdictions=preferred or None, config=cfg
        )
    elif mode == "dense":
        channels["dense"] = _dense_hits(
            query, system=system, jurisdictions=preferred or None, config=cfg
        )
    elif mode == "legacy":
        channels["legacy"] = _legacy_fuzzy_hits(system, query, limit=min(20, max(5, limit)))
    else:
        raise ValueError(f"unknown mode: {mode}")

    return reciprocal_rank_fusion(
        channels,
        k=cfg.rrf_k,
        query_has_citation=bool(extract_citations(query)),
        preferred_jurisdictions=set(preferred),
        preferred_systems={system},
        limit=limit,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate legal hybrid retrieval")
    parser.add_argument(
        "--gold",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "cn_law" / "gold_set.sample.jsonl",
    )
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--system", default="china")
    parser.add_argument(
        "--mode",
        default="hybrid",
        choices=["baseline", "exact", "bm25", "dense", "legacy", "hybrid", "hybrid+rerank"],
        help="评测通道；默认 hybrid",
    )
    parser.add_argument(
        "--modes",
        default="",
        help="逗号分隔多模式对比，如 baseline,bm25,dense,hybrid",
    )
    args = parser.parse_args()

    if not args.gold.exists():
        print(json.dumps({"success": False, "message": f"gold set missing: {args.gold}"}, ensure_ascii=False))
        return 1

    rows = _load_jsonl(args.gold)
    modes = [item.strip() for item in args.modes.split(",") if item.strip()] or [args.mode]
    summaries = {}

    for mode in modes:
        recalls = {5: [], 10: [], 20: []}
        mrrs: list[float] = []
        ndcgs: list[float] = []
        latencies: list[float] = []
        leaks: list[float] = []
        for row in rows:
            query = str(row.get("query") or "")
            expected = row.get("expected_articles") or []
            expected_pairs = [
                [str(item[0]), str(item[1])]
                for item in expected
                if isinstance(item, (list, tuple)) and len(item) >= 2
            ]
            jurisdictions = [str(row["jurisdiction"])] if row.get("jurisdiction") else None
            system = str(row.get("legal_system") or args.system)
            started = time.perf_counter()
            items = _run_mode(
                mode,
                query,
                system=system,
                jurisdictions=jurisdictions,
                limit=max(20, args.limit),
            )
            latencies.append(time.perf_counter() - started)
            for k in recalls:
                recalls[k].append(1.0 if _hit(expected_pairs, items, k) else 0.0)
            mrrs.append(_mrr(expected_pairs, items))
            ndcgs.append(_ndcg(expected_pairs, items, args.limit))
            forbidden = [str(x) for x in (row.get("must_not_include_jurisdictions") or [])]
            leaks.append(1.0 if _jurisdiction_leak(items, forbidden) else 0.0)

        n = len(rows) or 1
        summaries[mode] = {
            "samples": len(rows),
            "recall@5": sum(recalls[5]) / n,
            "recall@10": sum(recalls[10]) / n,
            "recall@20": sum(recalls[20]) / n,
            "mrr": sum(mrrs) / n,
            "ndcg": sum(ndcgs) / n,
            "jurisdiction_leak_rate": sum(leaks) / n,
            "latency_ms_avg": (sum(latencies) / n) * 1000.0,
            "latency_ms_p95": sorted(latencies)[max(0, int(math.ceil(0.95 * n)) - 1)] * 1000.0,
        }

    payload: dict[str, Any] = {
        "gold": str(args.gold),
        "modes": summaries if len(summaries) > 1 else summaries[modes[0]],
    }
    if len(summaries) == 1:
        # 单模式时保持扁平结构兼容旧消费方
        payload = {"gold": str(args.gold), **summaries[modes[0]], "mode": modes[0]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
