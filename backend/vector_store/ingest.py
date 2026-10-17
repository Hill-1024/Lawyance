"""从 RAG 原始数据构建法律 chunk，写入 Qdrant + BM25，并维护 manifest。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import LegalVectorConfig, REPO_ROOT, get_legal_vector_config
from .embeddings import embed_texts, probe_embedding_dimension
from .lexical import get_lexical_retriever
from .qdrant_client import (
    delete_by_source_ids,
    ensure_collection,
    health_check,
    upsert_chunks,
)
from .schema import (
    LawChunk,
    clean_law_name,
    content_hash,
    extract_revision_label,
    map_effective_status,
    normalize_article_number,
)

logger = logging.getLogger(__name__)

RAG_DATA = REPO_ROOT / "RAG" / "data"
CHINA_CATEGORIES = ("法律", "行政法规", "司法解释", "地方性法规")

# 中国法语料目录/代码 → ISO 国家码（与 retrieval.SYSTEM_TO_JURISDICTIONS 对齐）
_JURISDICTION_ALIASES = {
    "cn": "CN",
    "china": "CN",
    "中国": "CN",
}


def _normalize_jurisdiction(*candidates: str, default: str = "") -> str:
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        mapped = _JURISDICTION_ALIASES.get(text.casefold()) or _JURISDICTION_ALIASES.get(text.upper().casefold())
        if mapped:
            return mapped
        if len(text) == 2 and text.isalpha():
            return text.upper()
    return default


def _split_long_text(text: str, max_chars: int) -> list[str]:
    body = str(text or "").strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]
    parts: list[str] = []
    paragraphs = re.split(r"\n+", body)
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            for start in range(0, len(para), max_chars):
                parts.append(para[start : start + max_chars])
            continue
        candidate = f"{buf}\n{para}".strip() if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                parts.append(buf)
            buf = para
    if buf:
        parts.append(buf)
    return parts or [body[:max_chars]]


def _china_source_files(limit: int | None = None) -> list[Path]:
    files: list[Path] = []
    for category in CHINA_CATEGORIES:
        root = RAG_DATA / category
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if path.name == "index.json":
                continue
            files.append(path)
            if limit is not None and len(files) >= limit:
                return files
    return files


def iter_china_chunks(
    *,
    config: LegalVectorConfig | None = None,
    limit_files: int | None = None,
) -> Iterator[LawChunk]:
    cfg = config or get_legal_vector_config()
    for path in _china_source_files(limit_files):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skip china file %s: %s", path, exc)
            continue
        if not isinstance(payload, dict):
            continue
        law_name = clean_law_name(str(payload.get("law_name") or path.stem))
        short_name = clean_law_name(str(payload.get("short_name") or ""))
        articles = payload.get("articles")
        if not law_name or not isinstance(articles, dict) or not articles:
            continue
        effectiveness = str(payload.get("effectiveness") or "")
        source_id = str(payload.get("source_id") or path.stem)
        relative = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)
        law_type = path.parent.name if path.parent.name in CHINA_CATEGORIES else path.parts[-2]
        revision = extract_revision_label(law_name, effectiveness)
        effective_status = map_effective_status(effectiveness)
        implement = str(payload.get("implement_date") or "").replace(".", "-")
        url = str(payload.get("url") or "")
        for article_number, content in articles.items():
            number = str(article_number or "").strip()
            body = str(content or "").strip()
            if not number or not body:
                continue
            pieces = _split_long_text(body, cfg.max_chunk_chars)
            for index, piece in enumerate(pieces):
                chunk = LawChunk(
                    text=piece,
                    law_name=law_name,
                    short_name=short_name,
                    article_number=number,
                    article_number_normalized=normalize_article_number(number),
                    article_id="",
                    source_id=source_id,
                    source_file=relative,
                    content_hash=content_hash(piece),
                    law_type=law_type,
                    jurisdiction="CN",
                    legal_system="china",
                    effective_status=effective_status,
                    effective_date=implement,
                    revision_label=revision,
                    source_url=url,
                    chunk_index=index,
                    chunk_count=len(pieces),
                    embedding_model=cfg.embedding_model,
                    embedding_version=cfg.embedding_version,
                    chunking_version=cfg.chunking_version,
                )
                chunk.ensure_ids()
                yield chunk


def iter_all_chunks(
    *,
    limit_files: int | None = None,
    config: LegalVectorConfig | None = None,
) -> Iterator[LawChunk]:
    yield from iter_china_chunks(config=config, limit_files=limit_files)


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    cfg = get_legal_vector_config()
    target = path or cfg.manifest_path
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_index(
    *,
    limit_files: int | None = None,
    recreate_collection: bool = False,
    skip_qdrant: bool = False,
    skip_bm25: bool = False,
    config: LegalVectorConfig | None = None,
) -> dict[str, Any]:
    cfg = config or get_legal_vector_config()
    chunks = list(iter_all_chunks(limit_files=limit_files, config=cfg))
    # 过滤无正文 / 废止默认仍入库，检索时再 filter
    chunks = [chunk for chunk in chunks if chunk.text.strip()]
    stats: dict[str, Any] = {
        "chunk_count": len(chunks),
        "bm25_written": 0,
        "qdrant_written": 0,
        "skipped_embeddings": 0,
        "collection": cfg.collection_name(),
        "embedding_version": cfg.embedding_version,
        "chunking_version": cfg.chunking_version,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }

    if not skip_bm25:
        retriever = get_lexical_retriever(cfg)
        stats["bm25_written"] = retriever.index(chunks, replace=True)

    if not skip_qdrant:
        if not cfg.embedding_ready():
            raise RuntimeError("法律 embedding 未配置，无法写入 Qdrant")
        dim = probe_embedding_dimension(cfg)
        ensure_collection(vector_size=dim, config=cfg, recreate=recreate_collection)
        batch = max(1, cfg.vector_upsert_batch_size)
        written = 0
        skipped = 0
        for start in range(0, len(chunks), batch):
            batch_chunks = chunks[start : start + batch]
            texts = [chunk.embedding_text for chunk in batch_chunks]
            vectors = embed_texts(texts, config=cfg)
            ready_chunks: list[LawChunk] = []
            ready_vectors: list[list[float]] = []
            for chunk, vector in zip(batch_chunks, vectors):
                if not vector:
                    skipped += 1
                    continue
                ready_chunks.append(chunk)
                ready_vectors.append(vector)
            written += upsert_chunks(ready_chunks, ready_vectors, config=cfg)
        stats["qdrant_written"] = written
        stats["skipped_embeddings"] = skipped
        stats["vector_dim"] = dim
        stats["qdrant_health"] = health_check(cfg)

    by_system: dict[str, int] = {}
    source_hashes: dict[str, list[str]] = {}
    for chunk in chunks:
        by_system[chunk.legal_system] = by_system.get(chunk.legal_system, 0) + 1
        source_hashes.setdefault(chunk.source_id, []).append(chunk.content_hash)
    for source_id, hashes in source_hashes.items():
        source_hashes[source_id] = sorted(set(hashes))
    stats["by_legal_system"] = by_system
    stats["source_ids"] = sorted(source_hashes)[:5000]
    # 完整 hash 映射供增量 diff；体积可控时写入（过大则只保留抽样）
    if len(source_hashes) <= 20000:
        stats["source_content_hashes"] = source_hashes
    _write_manifest(cfg.manifest_path, stats)
    return stats


def _changed_sources_by_hash(
    previous: dict[str, Any],
    chunks: list[LawChunk],
) -> set[str]:
    """对比 manifest 中 source_id→content_hash[]，找出新增/删除/正文变更的 source。"""
    old_hashes = previous.get("source_content_hashes") or {}
    if not isinstance(old_hashes, dict):
        old_hashes = {}
    new_hashes: dict[str, set[str]] = {}
    for chunk in chunks:
        new_hashes.setdefault(chunk.source_id, set()).add(chunk.content_hash)
    old_ids = set(old_hashes) or set(previous.get("source_ids") or [])
    new_ids = set(new_hashes)
    changed = (new_ids - old_ids) | (old_ids - new_ids)
    for source_id in new_ids & old_ids:
        previous_set = set(old_hashes.get(source_id) or [])
        if previous_set != new_hashes[source_id]:
            changed.add(source_id)
    return changed


def update_index(
    *,
    changed_source_ids: Iterable[str] | None = None,
    config: LegalVectorConfig | None = None,
) -> dict[str, Any]:
    """按 content_hash / source_id 增量：删除旧 point 后 upsert 新 chunk。"""
    cfg = config or get_legal_vector_config()
    previous = load_manifest(cfg.manifest_path)
    # 若 embedding/chunking 版本变化则全量重建
    if previous and (
        previous.get("embedding_version") != cfg.embedding_version
        or previous.get("chunking_version") != cfg.chunking_version
    ):
        return build_index(recreate_collection=True, config=cfg)

    all_chunks = list(iter_all_chunks(config=cfg))
    targets = set(changed_source_ids or [])
    if not targets:
        targets = _changed_sources_by_hash(previous, all_chunks)

    if not targets:
        return {"updated": 0, "message": "no changes"}

    selected = [chunk for chunk in all_chunks if chunk.source_id in targets]
    delete_by_source_ids(sorted(targets), config=cfg)
    retriever = get_lexical_retriever(cfg)
    retriever.delete_by_source_ids(targets)

    bm25_written = 0
    qdrant_written = 0
    if selected:
        bm25_written = retriever.index(selected, replace=False)
        if cfg.embedding_ready():
            try:
                dim = probe_embedding_dimension(cfg)
                ensure_collection(vector_size=dim, config=cfg, recreate=False)
                texts = [chunk.embedding_text for chunk in selected]
                vectors = embed_texts(texts, config=cfg)
                ready_chunks = []
                ready_vectors = []
                for chunk, vector in zip(selected, vectors):
                    if vector:
                        ready_chunks.append(chunk)
                        ready_vectors.append(vector)
                qdrant_written = upsert_chunks(ready_chunks, ready_vectors, config=cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("incremental qdrant upsert failed: %s", exc)

    by_system: dict[str, int] = {}
    source_hashes: dict[str, list[str]] = {}
    for chunk in all_chunks:
        by_system[chunk.legal_system] = by_system.get(chunk.legal_system, 0) + 1
        source_hashes.setdefault(chunk.source_id, []).append(chunk.content_hash)
    for source_id, hashes in source_hashes.items():
        source_hashes[source_id] = sorted(set(hashes))

    stats = {
        "updated_sources": len(targets),
        "updated_chunks": len(selected),
        "bm25_written": bm25_written,
        "qdrant_written": qdrant_written,
        "chunk_count": len(all_chunks),
        "collection": cfg.collection_name(),
        "embedding_version": cfg.embedding_version,
        "chunking_version": cfg.chunking_version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "by_legal_system": by_system,
        "source_ids": sorted(source_hashes)[:5000],
    }
    if len(source_hashes) <= 20000:
        stats["source_content_hashes"] = source_hashes
    _write_manifest(cfg.manifest_path, stats)
    return stats


def check_index(
    config: LegalVectorConfig | None = None,
    *,
    sample_size: int = 5,
) -> dict[str, Any]:
    cfg = config or get_legal_vector_config()
    manifest = load_manifest(cfg.manifest_path)
    report: dict[str, Any] = {
        "manifest": {
            key: manifest.get(key)
            for key in (
                "chunk_count",
                "collection",
                "embedding_version",
                "chunking_version",
                "vector_dim",
                "built_at",
                "by_legal_system",
            )
        },
        "bm25_count": 0,
        "qdrant": health_check(cfg),
        "checks": {},
    }
    try:
        report["bm25_count"] = get_lexical_retriever(cfg).count()
    except Exception as exc:  # noqa: BLE001
        report["bm25_error"] = str(exc)

    checks = report["checks"]
    checks["bm25_nonempty"] = report["bm25_count"] > 0
    checks["manifest_chunk_count"] = int(manifest.get("chunk_count") or 0)
    if manifest.get("vector_dim"):
        checks["vector_dim"] = manifest.get("vector_dim")

    qdrant = report["qdrant"]
    if qdrant.get("ok") and qdrant.get("collection_exists"):
        try:
            from .qdrant_client import count_points

            points = count_points(cfg)
            report["qdrant_points"] = points
            checks["qdrant_points_positive"] = points > 0
            expected = int(manifest.get("qdrant_written") or manifest.get("chunk_count") or 0)
            if expected:
                checks["qdrant_count_close_to_manifest"] = abs(points - expected) <= max(5, expected // 20)
        except Exception as exc:  # noqa: BLE001
            report["qdrant_count_error"] = str(exc)

    # payload / 来源完整性抽样（BM25 sidecar）
    samples: list[dict[str, Any]] = []
    try:
        retriever = get_lexical_retriever(cfg)
        hits = retriever.search("合同 违约", limit=max(1, sample_size))
        required = (
            "law_name",
            "article_number",
            "jurisdiction",
            "legal_system",
            "effective_status",
            "source_id",
            "content_hash",
        )
        for hit in hits[:sample_size]:
            payload = {
                "law_name": hit.law_name,
                "article_number": hit.article_number,
                "jurisdiction": hit.jurisdiction,
                "legal_system": hit.legal_system,
                "effective_status": hit.effective_status,
                "source_id": hit.source_id,
                "content_hash": hit.content_hash[:12] if hit.content_hash else "",
            }
            payload["ok"] = all(bool(getattr(hit, field, "")) for field in required)
            samples.append(payload)
        checks["payload_sample_ok"] = bool(samples) and all(item["ok"] for item in samples)
    except Exception as exc:  # noqa: BLE001
        report["sample_error"] = str(exc)
    report["payload_samples"] = samples

    source_ids = manifest.get("source_ids") or []
    checks["source_ids_present"] = isinstance(source_ids, list) and len(source_ids) > 0
    return report
