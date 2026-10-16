"""去重、RRF 融合与元数据加权。"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import LawChunk


def merge_chunk(existing: LawChunk, incoming: LawChunk) -> LawChunk:
    for route in incoming.routes:
        if route not in existing.routes:
            existing.routes.append(route)
    for key, value in incoming.scores.items():
        if key not in existing.scores or float(value) > float(existing.scores.get(key, 0)):
            existing.scores[key] = float(value)
    # 优先保留更完整正文
    if len(incoming.text or "") > len(existing.text or ""):
        existing.text = incoming.text
    return existing


def dedupe_chunks(chunks: Iterable[LawChunk]) -> list[LawChunk]:
    """按 (jurisdiction, source_id, article_normalized, revision) 去重，同条多 chunk 保留最高分。"""
    best: dict[tuple[str, str, str, str], LawChunk] = {}
    for chunk in chunks:
        chunk.ensure_ids()
        key = chunk.dedupe_key()
        current = best.get(key)
        if current is None:
            best[key] = chunk
            continue
        current_score = max(
            float(current.scores.get("dense", 0)),
            float(current.scores.get("lexical", 0)),
            float(current.scores.get("legacy", 0)),
            float(current.scores.get("exact", 0)),
        )
        incoming_score = max(
            float(chunk.scores.get("dense", 0)),
            float(chunk.scores.get("lexical", 0)),
            float(chunk.scores.get("legacy", 0)),
            float(chunk.scores.get("exact", 0)),
        )
        if incoming_score >= current_score:
            best[key] = merge_chunk(chunk, current)
        else:
            best[key] = merge_chunk(current, chunk)
    return list(best.values())


def exact_bonus(chunk: LawChunk, *, query_has_citation: bool) -> float:
    if float(chunk.scores.get("exact", 0)) > 0:
        return 2.0 if query_has_citation else 1.0
    return 0.0


def metadata_bonus(
    chunk: LawChunk,
    *,
    preferred_jurisdictions: set[str] | None = None,
    preferred_systems: set[str] | None = None,
) -> float:
    bonus = 0.0
    if chunk.effective_status == "in_force":
        bonus += 0.15
    elif chunk.effective_status == "not_yet_in_force":
        bonus -= 0.2
    elif chunk.effective_status == "repealed":
        bonus -= 0.5
    if preferred_jurisdictions and chunk.jurisdiction in preferred_jurisdictions:
        bonus += 0.2
    if preferred_systems and chunk.legal_system in preferred_systems:
        bonus += 0.1
    return bonus


def reciprocal_rank_fusion(
    channels: dict[str, list[LawChunk]],
    *,
    k: int = 60,
    query_has_citation: bool = False,
    preferred_jurisdictions: set[str] | None = None,
    preferred_systems: set[str] | None = None,
    limit: int = 20,
) -> list[LawChunk]:
    """RRF(d) = Σ 1/(k+rank) + exact_bonus + metadata_bonus。"""
    pooled: dict[tuple[str, str, str, str], LawChunk] = {}
    scores: dict[tuple[str, str, str, str], float] = defaultdict(float)

    for channel_name, hits in channels.items():
        for rank, chunk in enumerate(hits, start=1):
            chunk.ensure_ids()
            key = chunk.dedupe_key()
            if key not in pooled:
                pooled[key] = chunk
            else:
                pooled[key] = merge_chunk(pooled[key], chunk)
            scores[key] += 1.0 / (float(k) + float(rank))
            pooled[key].scores[f"rrf_{channel_name}"] = 1.0 / (float(k) + float(rank))

    ranked: list[tuple[float, LawChunk]] = []
    for key, chunk in pooled.items():
        total = scores[key]
        total += exact_bonus(chunk, query_has_citation=query_has_citation)
        total += metadata_bonus(
            chunk,
            preferred_jurisdictions=preferred_jurisdictions,
            preferred_systems=preferred_systems,
        )
        chunk.scores["rrf"] = total
        ranked.append((total, chunk))

    ranked.sort(
        key=lambda item: (
            -item[0],
            -float(item[1].scores.get("exact", 0)),
            len(item[1].law_name),
            len(item[1].text),
        )
    )
    return [chunk for _, chunk in ranked[: max(1, limit)]]
