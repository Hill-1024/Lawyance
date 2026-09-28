from __future__ import annotations

import math
from typing import Any

from .state import *
from .utils import *

def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return _clamp(numerator / (left_norm * right_norm))

def _rag_profile_for_query(
    query_features: dict[str, float],
    query_entities: set[str],
) -> str:
    tags = set(query_features)
    if "undo_revision" in tags:
        return "revision"
    if tags & {"payment_fact", "delivery_fact", "contract_liability"}:
        return "legal_fact"
    if tags & {"memory_scope", "attention_control", "retrieval", "architecture_boundary"}:
        return "architecture_memory"
    if query_entities:
        return "entity_heavy"
    return "general"

def _rag_weights_for_profile(profile: str, embedding_active: bool) -> dict[str, float]:
    multipliers = _RAG_PROFILE_MULTIPLIERS.get(profile, {})
    weights = {
        name: round(weight * float(multipliers.get(name, 1.0)), 4)
        for name, weight in _RAG_BASE_WEIGHTS.items()
    }
    if not embedding_active:
        weights["embedding"] = 0.0
    return weights

def _kind_signal(kind: str, memory_kind: Any) -> float:
    if kind == "focus":
        return 1.0
    if memory_kind == "constraint":
        return 0.96
    if kind == "fact":
        return 0.82
    return 0.42

def _rag_relevance_threshold(profile: str) -> float:
    if profile == "legal_fact":
        return 1.25
    if profile == "architecture_memory":
        return 1.2
    if profile == "revision":
        return 1.05
    return RAG_DEFAULT_RELEVANCE_THRESHOLD

def _rag_ranking_config(
    query_features: dict[str, float],
    query_entities: set[str],
    *,
    embedding_active: bool = False,
) -> dict[str, Any]:
    profile = _rag_profile_for_query(query_features, query_entities)
    weights = _rag_weights_for_profile(profile, embedding_active)
    return {
        "profile": profile,
        "embedding_enabled": embedding_active,
        "weights": weights,
        "threshold": _rag_relevance_threshold(profile),
    }

def _rag_score(
    *,
    weights: dict[str, float],
    embedding: float,
    semantic: float,
    entity: float,
    lexical: float,
    fuzzy: float,
    substring: float,
    priority: float,
    confidence: float,
    recency: float,
    kind_signal: float,
    pinned: bool,
) -> tuple[float, float, dict[str, float]]:
    weighted_signals = {
        "embedding": embedding,
        "semantic": semantic,
        "entity": entity,
        "lexical": lexical,
        "fuzzy": fuzzy,
        "substring": substring,
        "priority": priority,
        "confidence": confidence,
        "recency": recency,
        "kind": kind_signal,
        "pinned": 1.0 if pinned else 0.0,
    }
    contributions = {
        name: round(_clamp(value) * weights.get(name, 0.0), 4)
        for name, value in weighted_signals.items()
        if weights.get(name, 0.0) > 0
    }
    score = round(sum(contributions.values()), 4)
    max_score = sum(weights.values()) or 1.0
    rag_weight = round(_clamp(score / max_score), 4)
    return score, rag_weight, contributions

__all__ = [name for name in globals() if not name.startswith("__")]
