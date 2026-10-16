"""统一混合检索入口：精确 + dense + BM25 + legacy fuzzy → RRF → 可选精排。"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .config import LegalVectorConfig, get_legal_vector_config
from .embeddings import embed_texts, embedding_available
from .fusion import reciprocal_rank_fusion
from .lexical import get_lexical_retriever
from .qdrant_client import dense_search, health_check
from .reranker import rerank_chunks, reranker_available
from .schema import LawChunk, clean_law_name, map_effective_status, normalize_article_number

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(
    r"《(?P<title>[^》\n]{2,80})》(?P<number>第[一二三四五六七八九十百千万零〇两0-9]+条(?:之[一二三四五六七八九十百千万零〇两0-9]+)?)"
)

SYSTEM_TO_JURISDICTIONS = {
    "china": ["CN"],
    "civil": ["ID", "TH", "VN"],
    "islamic": ["MY", "ID"],
    "common": ["MM", "SG"],
}


def hybrid_enabled(config: LegalVectorConfig | None = None) -> bool:
    cfg = config or get_legal_vector_config()
    return bool(cfg.vector_retrieval_enabled and cfg.vector_db_enabled)


def extract_citations(query: str) -> list[tuple[str, str]]:
    return [(m.group("title"), m.group("number")) for m in CITATION_RE.finditer(query or "")]


def _legacy_fuzzy_hits(system: str, query: str, limit: int = 10) -> list[LawChunk]:
    items: list[dict[str, Any]] = []
    try:
        if system == "china":
            from RAG.law_data_search import law_fuzzy_search

            payload = json.loads(law_fuzzy_search(query, limit=limit))
            items = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            jurisdiction = "CN"
            legal_system = "china"
        elif system == "civil":
            from RAG.civil_law import fuzzy_search

            payload = json.loads(fuzzy_search(query, limit))
            items = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            jurisdiction = ""
            legal_system = "civil"
        elif system == "islamic":
            from RAG.islamic_law import semantic_search

            payload = json.loads(semantic_search(query, limit))
            items = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            jurisdiction = ""
            legal_system = "islamic"
        else:
            from RAG.common_law import fuzzy_search

            payload = json.loads(fuzzy_search(query, limit))
            items = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
            jurisdiction = ""
            legal_system = "common"
    except Exception as exc:  # noqa: BLE001
        logger.warning("legacy fuzzy failed: %s", exc)
        return []

    hits: list[LawChunk] = []
    for rank, item in enumerate(items, start=1):
        law_name = str(item.get("law_name") or "")
        article_number = str(item.get("article_number") or "")
        content = str(item.get("content") or "")
        if not content:
            continue
        country = str(item.get("country") or item.get("jurisdiction") or jurisdiction or "")
        chunk = LawChunk(
            text=content,
            law_name=clean_law_name(law_name),
            short_name=str(item.get("short_name") or ""),
            article_number=article_number,
            article_number_normalized=normalize_article_number(article_number),
            article_id="",
            source_id=str(item.get("source_id") or item.get("cli") or law_name),
            source_file=str(item.get("source_file") or ""),
            content_hash="",
            law_type=str(item.get("law_type") or item.get("category") or ""),
            jurisdiction=str(country or jurisdiction or "CN"),
            legal_system=legal_system,
            effective_status=map_effective_status(
                str(item.get("effectiveness") or ""),
                str(item.get("status") or ""),
            ),
            source_url=str(item.get("url") or ""),
            revision_label=str(item.get("revision_label") or ""),
        )
        chunk.ensure_ids()
        chunk.scores["legacy"] = float(max(1, limit - rank + 1))
        chunk.scores["legacy_rank"] = float(rank)
        chunk.routes.append("legacy")
        hits.append(chunk)
    return hits


def _exact_hits(system: str, query: str) -> list[LawChunk]:
    citations = extract_citations(query)
    if not citations:
        return []
    hits: list[LawChunk] = []
    for title, number in citations:
        try:
            if system == "china":
                from RAG.law_data_search import law_exact_search

                payload = json.loads(law_exact_search(title, number))
                data = payload.get("data") if payload.get("success") else None
                jurisdiction = "CN"
                legal_system = "china"
            elif system == "civil":
                from RAG.civil_law import exact_search

                payload = json.loads(exact_search(title, number))
                data = payload.get("data") if payload.get("success") else None
                jurisdiction = str((data or {}).get("country") or "")
                legal_system = "civil"
            elif system == "islamic":
                from RAG.islamic_law import exact_search

                payload = json.loads(exact_search(title, number))
                data = payload.get("data") if payload.get("success") else None
                jurisdiction = str((data or {}).get("country") or "")
                legal_system = "islamic"
            else:
                from RAG.common_law import exact_search

                payload = json.loads(exact_search(title, number))
                data = payload.get("data") if payload.get("success") else None
                jurisdiction = str((data or {}).get("country") or "")
                legal_system = "common"
        except Exception as exc:  # noqa: BLE001
            logger.warning("exact search failed: %s", exc)
            continue
        if not isinstance(data, dict):
            continue
        content = str(data.get("content") or "")
        if not content:
            continue
        law_name = str(data.get("law_name") or title)
        article_number = str(data.get("article_number") or number)
        chunk = LawChunk(
            text=content,
            law_name=clean_law_name(law_name),
            short_name=str(data.get("short_name") or ""),
            article_number=article_number,
            article_number_normalized=normalize_article_number(article_number),
            article_id="",
            source_id=str(data.get("source_id") or data.get("cli") or law_name),
            source_file=str(data.get("source_file") or ""),
            content_hash="",
            law_type=str(data.get("law_type") or data.get("category") or ""),
            jurisdiction=jurisdiction or "CN",
            legal_system=legal_system,
            effective_status="in_force",
            source_url=str(data.get("url") or ""),
        )
        chunk.ensure_ids()
        chunk.scores["exact"] = 100.0
        chunk.scores["exact_rank"] = 1.0
        chunk.routes.append("exact")
        hits.append(chunk)
    return hits


def _dense_hits(
    query: str,
    *,
    system: str,
    jurisdictions: list[str] | None,
    config: LegalVectorConfig,
) -> list[LawChunk]:
    if not embedding_available(config):
        return []
    health = health_check(config)
    if not health.get("ok") or not health.get("collection_exists"):
        return []
    vectors = embed_texts([query], config=config)
    if not vectors or not vectors[0]:
        return []
    try:
        return dense_search(
            vectors[0],
            limit=config.vector_search_limit,
            jurisdictions=jurisdictions,
            legal_systems=[system] if system else None,
            effective_statuses=["in_force"],
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("dense search failed: %s", exc)
        return []


def _bm25_hits(
    query: str,
    *,
    system: str,
    jurisdictions: list[str] | None,
    config: LegalVectorConfig,
) -> list[LawChunk]:
    if not config.bm25_enabled:
        return []
    try:
        retriever = get_lexical_retriever(config)
        return retriever.search(
            query,
            filters={
                "jurisdictions": jurisdictions or [],
                "legal_systems": [system] if system else [],
                "effective_statuses": ["in_force"],
            },
            limit=config.bm25_top_k,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("bm25 search failed: %s", exc)
        return []


def hybrid_search(
    query: str,
    *,
    jurisdiction_system: str = "china",
    jurisdictions: list[str] | None = None,
    limit: int | None = None,
    config: LegalVectorConfig | None = None,
    legacy_fetcher: Callable[[str, str, int], list[LawChunk]] | None = None,
) -> dict[str, Any]:
    """返回结构化混合检索结果；失败时仍尽量带回 legacy 通道。"""
    cfg = config or get_legal_vector_config()
    system = (jurisdiction_system or "china").strip().lower() or "china"
    preferred_jurisdictions = jurisdictions or SYSTEM_TO_JURISDICTIONS.get(system, ["CN"])
    final_k = int(limit or cfg.final_retrieval_k)
    query_text = str(query or "").strip()
    channels: dict[str, list[LawChunk]] = {}
    degraded: list[str] = []

    exact = _exact_hits(system, query_text)
    if exact:
        channels["exact"] = exact

    legacy_fn = legacy_fetcher or (lambda sys, q, lim: _legacy_fuzzy_hits(sys, q, lim))
    try:
        channels["legacy"] = legacy_fn(system, query_text, min(20, max(5, final_k * 2)))
    except Exception as exc:  # noqa: BLE001
        degraded.append(f"legacy:{exc}")
        channels["legacy"] = []

    if hybrid_enabled(cfg):
        with ThreadPoolExecutor(max_workers=2) as pool:
            dense_future = pool.submit(
                _dense_hits,
                query_text,
                system=system,
                jurisdictions=preferred_jurisdictions,
                config=cfg,
            )
            bm25_future = pool.submit(
                _bm25_hits,
                query_text,
                system=system,
                jurisdictions=preferred_jurisdictions,
                config=cfg,
            )
            try:
                channels["dense"] = dense_future.result()
            except Exception as exc:  # noqa: BLE001
                degraded.append(f"dense:{exc}")
                channels["dense"] = []
            try:
                channels["bm25"] = bm25_future.result()
            except Exception as exc:  # noqa: BLE001
                degraded.append(f"bm25:{exc}")
                channels["bm25"] = []
    else:
        degraded.append("vector_retrieval_disabled")

    fused = reciprocal_rank_fusion(
        channels,
        k=cfg.rrf_k,
        query_has_citation=bool(extract_citations(query_text)),
        preferred_jurisdictions=set(preferred_jurisdictions),
        preferred_systems={system},
        limit=cfg.hybrid_top_k,
    )

    if reranker_available(cfg) and fused:
        try:
            fused = rerank_chunks(query_text, fused, config=cfg)
        except Exception as exc:  # noqa: BLE001
            degraded.append(f"reranker:{exc}")

    # 精确命中硬提升到最前
    exact_keys = {chunk.dedupe_key() for chunk in exact}
    if exact_keys:
        head = [chunk for chunk in fused if chunk.dedupe_key() in exact_keys]
        tail = [chunk for chunk in fused if chunk.dedupe_key() not in exact_keys]
        fused = head + tail

    results = fused[: max(1, final_k)]
    return {
        "success": bool(results),
        "query": query_text,
        "jurisdiction_system": system,
        "items": results,
        "degraded": degraded,
        "channel_counts": {name: len(hits) for name, hits in channels.items()},
    }


def format_hybrid_result_text(items: list[LawChunk]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        content = item.text or ""
        snippet = content if len(content) <= 220 else f"{content[:220]}..."
        source = f"\n来源: {item.source_url}" if item.source_url else ""
        lines.append(f"{index}. 《{item.law_name}》{item.article_number}\n{snippet}{source}")
    return "\n\n".join(lines)
