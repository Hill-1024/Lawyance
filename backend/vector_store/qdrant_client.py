"""Qdrant collection 管理、upsert 与 dense search。"""

from __future__ import annotations

import logging
from typing import Any

from .config import LegalVectorConfig, get_legal_vector_config
from .schema import LawChunk, PAYLOAD_INDEX_FIELDS

logger = logging.getLogger(__name__)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except ImportError:  # pragma: no cover - optional until dependency installed
    QdrantClient = None  # type: ignore[assignment,misc]
    qmodels = None  # type: ignore[assignment]


class QdrantUnavailable(RuntimeError):
    pass


def _require_qdrant() -> None:
    if QdrantClient is None or qmodels is None:
        raise QdrantUnavailable("qdrant-client 未安装")


def build_client(config: LegalVectorConfig | None = None) -> Any:
    _require_qdrant()
    cfg = config or get_legal_vector_config()
    kwargs: dict[str, Any] = {"url": cfg.qdrant_url, "timeout": 30}
    if cfg.qdrant_api_key:
        kwargs["api_key"] = cfg.qdrant_api_key
    return QdrantClient(**kwargs)


def health_check(config: LegalVectorConfig | None = None) -> dict[str, Any]:
    cfg = config or get_legal_vector_config()
    if not cfg.vector_db_enabled:
        return {"ok": False, "reason": "vector_db_disabled"}
    try:
        client = build_client(cfg)
        collections = client.get_collections()
        names = [item.name for item in collections.collections]
        collection = cfg.collection_name()
        return {
            "ok": True,
            "collection": collection,
            "collection_exists": collection in names,
            "collections": names,
        }
    except Exception as exc:  # noqa: BLE001 - surface as health payload
        logger.warning("qdrant health failed: %s", exc)
        return {"ok": False, "reason": str(exc)}


def _distance(cfg: LegalVectorConfig):
    _require_qdrant()
    mapping = {
        "cosine": qmodels.Distance.COSINE,
        "euclid": qmodels.Distance.EUCLID,
        "dot": qmodels.Distance.DOT,
    }
    return mapping.get(cfg.vector_distance.lower(), qmodels.Distance.COSINE)


def ensure_collection(
    *,
    vector_size: int,
    config: LegalVectorConfig | None = None,
    recreate: bool = False,
) -> str:
    cfg = config or get_legal_vector_config()
    client = build_client(cfg)
    name = cfg.collection_name()
    exists = False
    try:
        client.get_collection(name)
        exists = True
    except Exception:  # noqa: BLE001
        exists = False

    if exists and recreate:
        client.delete_collection(name)
        exists = False

    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=int(vector_size), distance=_distance(cfg)),
        )
        for field_name in PAYLOAD_INDEX_FIELDS:
            try:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("payload index %s: %s", field_name, exc)
    return name


def upsert_chunks(
    chunks: list[LawChunk],
    vectors: list[list[float]],
    *,
    config: LegalVectorConfig | None = None,
) -> int:
    if len(chunks) != len(vectors):
        raise ValueError("chunks 与 vectors 数量不一致")
    cfg = config or get_legal_vector_config()
    client = build_client(cfg)
    name = cfg.collection_name()
    points = []
    for chunk, vector in zip(chunks, vectors):
        if not vector:
            continue
        chunk.ensure_ids()
        chunk.embedding_model = cfg.embedding_model
        chunk.embedding_version = cfg.embedding_version
        chunk.chunking_version = cfg.chunking_version
        points.append(
            qmodels.PointStruct(
                id=chunk.point_id,
                vector=vector,
                payload=chunk.to_payload(),
            )
        )
    if not points:
        return 0
    batch = max(1, cfg.vector_upsert_batch_size)
    written = 0
    for start in range(0, len(points), batch):
        client.upsert(collection_name=name, points=points[start : start + batch])
        written += len(points[start : start + batch])
    return written


def delete_by_source_ids(source_ids: list[str], *, config: LegalVectorConfig | None = None) -> None:
    if not source_ids:
        return
    cfg = config or get_legal_vector_config()
    client = build_client(cfg)
    client.delete(
        collection_name=cfg.collection_name(),
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="source_id",
                        match=qmodels.MatchAny(any=list(source_ids)),
                    )
                ]
            )
        ),
    )


def _build_filter(
    *,
    jurisdictions: list[str] | None,
    legal_systems: list[str] | None,
    effective_statuses: list[str] | None,
) -> Any | None:
    _require_qdrant()
    must = []
    if jurisdictions:
        must.append(
            qmodels.FieldCondition(
                key="jurisdiction",
                match=qmodels.MatchAny(any=list(jurisdictions)),
            )
        )
    if legal_systems:
        must.append(
            qmodels.FieldCondition(
                key="legal_system",
                match=qmodels.MatchAny(any=list(legal_systems)),
            )
        )
    if effective_statuses:
        must.append(
            qmodels.FieldCondition(
                key="effective_status",
                match=qmodels.MatchAny(any=list(effective_statuses)),
            )
        )
    if not must:
        return None
    return qmodels.Filter(must=must)


def _query_points(
    client: Any,
    *,
    collection_name: str,
    query_vector: list[float],
    query_filter: Any | None,
    limit: int,
) -> list[Any]:
    """兼容 qdrant-client≥1.14 的 query_points；旧版回退 search。"""
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=max(1, int(limit)),
            with_payload=True,
        )
        return list(getattr(response, "points", None) or [])
    # 旧客户端（仅测试/降级路径）
    search = getattr(client, "search", None)
    if callable(search):
        return list(
            search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
            )
            or []
        )
    raise QdrantUnavailable("当前 qdrant-client 不支持 query_points/search")


def dense_search(
    query_vector: list[float],
    *,
    limit: int = 50,
    jurisdictions: list[str] | None = None,
    legal_systems: list[str] | None = None,
    effective_statuses: list[str] | None = None,
    config: LegalVectorConfig | None = None,
) -> list[LawChunk]:
    cfg = config or get_legal_vector_config()
    client = build_client(cfg)
    query_filter = _build_filter(
        jurisdictions=jurisdictions,
        legal_systems=legal_systems,
        effective_statuses=effective_statuses or ["in_force"],
    )
    results = _query_points(
        client,
        collection_name=cfg.collection_name(),
        query_vector=query_vector,
        query_filter=query_filter,
        limit=limit,
    )
    hits: list[LawChunk] = []
    for rank, point in enumerate(results, start=1):
        payload = dict(getattr(point, "payload", None) or {})
        chunk = LawChunk.from_payload(payload, point_id=str(getattr(point, "id", "")))
        chunk.scores["dense"] = float(getattr(point, "score", 0.0) or 0.0)
        chunk.scores["dense_rank"] = float(rank)
        chunk.routes.append("dense")
        hits.append(chunk)
    return hits


def count_points(config: LegalVectorConfig | None = None) -> int:
    cfg = config or get_legal_vector_config()
    client = build_client(cfg)
    info = client.get_collection(cfg.collection_name())
    return int(getattr(info, "points_count", 0) or 0)
