"""交叉编码器精排（SiliconFlow 风格 HTTP rerank API）。"""

from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from .config import LegalVectorConfig, get_legal_vector_config
from .schema import LawChunk

logger = logging.getLogger(__name__)

_FAILURE_UNTIL = 0.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None


def _ssl_context() -> ssl.SSLContext | None:
    import os

    cafile = (
        os.getenv("LAWVER_RERANKER_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or (certifi.where() if certifi is not None else None)
    )
    if not cafile:
        return None
    return ssl.create_default_context(cafile=cafile)


def reranker_available(config: LegalVectorConfig | None = None) -> bool:
    cfg = config or get_legal_vector_config()
    if not cfg.reranker_enabled:
        return False
    if time.time() < _FAILURE_UNTIL:
        return False
    return bool(cfg.reranker_base_url and cfg.reranker_api_key and cfg.reranker_model)


def mark_reranker_failure(seconds: float = 60.0) -> None:
    global _FAILURE_UNTIL
    _FAILURE_UNTIL = time.time() + seconds


def clear_reranker_failure() -> None:
    global _FAILURE_UNTIL
    _FAILURE_UNTIL = 0.0


def _candidate_text(chunk: LawChunk) -> str:
    return (
        f"法律名称：{chunk.law_name}\n"
        f"条号：{chunk.article_number}\n"
        f"法域：{chunk.jurisdiction}\n"
        f"正文：{chunk.text}"
    )


def _parse_scores(data: Any, count: int) -> list[float] | None:
    if not isinstance(data, dict):
        return None
    # SiliconFlow / Cohere-like: {"results":[{"index":0,"relevance_score":0.9}, ...]}
    results = data.get("results")
    if isinstance(results, list) and results:
        scores = [0.0 for _ in range(count)]
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if not isinstance(index, int) or index < 0 or index >= count or index in seen:
                return None
            try:
                scores[index] = float(score)
            except (TypeError, ValueError):
                return None
            seen.add(index)
        if len(seen) != count:
            # 允许部分返回：未返回的保持 0
            pass
        return scores
    # OpenAI-like data list
    raw = data.get("data")
    if isinstance(raw, list) and len(raw) == count:
        out: list[float] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    out.append(float(item.get("score", item.get("relevance_score", 0))))
                except (TypeError, ValueError):
                    out.append(0.0)
            else:
                out.append(0.0)
        return out
    return None


def request_rerank(
    query: str,
    documents: list[str],
    *,
    config: LegalVectorConfig | None = None,
) -> list[float] | None:
    cfg = config or get_legal_vector_config()
    if not documents or not reranker_available(cfg):
        return None
    payload = json.dumps(
        {
            "model": cfg.reranker_model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    # SiliconFlow: POST /rerank
    url = f"{cfg.reranker_base_url.rstrip('/')}/rerank"
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {cfg.reranker_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=float(cfg.reranker_timeout),
            context=_ssl_context(),
        ) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        mark_reranker_failure()
        logger.warning("reranker failed: %s", exc)
        return None
    if len(raw) > _MAX_RESPONSE_BYTES:
        mark_reranker_failure()
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        mark_reranker_failure()
        return None
    return _parse_scores(data, len(documents))


def rerank_chunks(
    query: str,
    chunks: list[LawChunk],
    *,
    config: LegalVectorConfig | None = None,
) -> list[LawChunk]:
    """对 TopN 精排后按 cross_encoder 全排序截断；失败时原样返回 RRF 结果。"""
    cfg = config or get_legal_vector_config()
    if not chunks:
        return []
    if not reranker_available(cfg):
        return chunks
    top_k = max(1, cfg.reranker_top_k)
    final_k = max(1, cfg.reranker_final_k)
    top = chunks[:top_k]
    documents = [_candidate_text(chunk) for chunk in top]
    scores = request_rerank(query, documents, config=cfg)
    if scores is None:
        return chunks
    scored: list[tuple[float, LawChunk]] = []
    for chunk, score in zip(top, scores):
        chunk.scores["cross_encoder_score"] = float(score)
        chunk.scores["cross_encoder"] = float(score)
        if "reranker" not in chunk.routes:
            chunk.routes.append("reranker")
        scored.append((float(score), chunk))
    scored.sort(key=lambda item: -item[0])
    model_name = cfg.reranker_model or ""
    ordered: list[LawChunk] = []
    for rank, (_score, chunk) in enumerate(scored, start=1):
        chunk.scores["cross_encoder_rank"] = float(rank)
        if model_name:
            chunk.reranker_model = model_name
        ordered.append(chunk)
    # 未进入精排窗口的候选按原 RRF 顺序接在后面，再截断 final_k
    seen = {id(chunk) for chunk in ordered}
    for chunk in chunks[top_k:]:
        if id(chunk) not in seen:
            ordered.append(chunk)
    return ordered[:final_k]
