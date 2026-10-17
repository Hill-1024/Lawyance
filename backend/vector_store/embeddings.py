"""法律文档批量 embedding（独立于对话记忆）。"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from .config import LegalVectorConfig, get_legal_vector_config

logger = logging.getLogger(__name__)

_FAILURE_UNTIL = 0.0
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TRANSIENT_ERRORS = (
    OSError,
    TimeoutError,
    urllib.error.URLError,
    http.client.HTTPException,
    http.client.IncompleteRead,
)

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None


def _ssl_context() -> ssl.SSLContext | None:
    cafile = (
        __import__("os").getenv("LAWVER_LEGAL_EMBEDDING_CA_BUNDLE")
        or __import__("os").getenv("SSL_CERT_FILE")
        or (certifi.where() if certifi is not None else None)
    )
    if not cafile:
        return None
    return ssl.create_default_context(cafile=cafile)


def _clip(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    return value[:max_chars]


def _coerce_embedding(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or not raw:
        return None
    try:
        vector = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if not any(vector):
        return None
    return vector


def embedding_available(config: LegalVectorConfig | None = None) -> bool:
    cfg = config or get_legal_vector_config()
    if time.time() < _FAILURE_UNTIL:
        return False
    return cfg.embedding_ready()


def mark_embedding_failure(seconds: float = 60.0) -> None:
    global _FAILURE_UNTIL
    _FAILURE_UNTIL = time.time() + seconds


def clear_embedding_failure() -> None:
    global _FAILURE_UNTIL
    _FAILURE_UNTIL = 0.0


def request_embedding_batch(
    texts: list[str],
    *,
    config: LegalVectorConfig | None = None,
) -> list[list[float] | None]:
    cfg = config or get_legal_vector_config()
    if not embedding_available(cfg):
        return [None for _ in texts]
    clipped = [_clip(text, cfg.embedding_max_chars) for text in texts]
    payload = json.dumps(
        {"model": cfg.embedding_model, "input": clipped},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{cfg.embedding_base_url}/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {cfg.embedding_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=float(cfg.embedding_timeout),
            context=_ssl_context(),
        ) as response:
            # 勿对 chunked 响应传 read(amt)：易触发 IncompleteRead
            raw_response = response.read()
    except urllib.error.HTTPError as exc:
        mark_embedding_failure(seconds=30.0)
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            body = ""
        logger.warning("legal embedding HTTP %s: %s", exc.code, body or exc)
        return [None for _ in texts]
    except _TRANSIENT_ERRORS as exc:
        # 瞬时断流：短熔断，便于上层立刻重试
        mark_embedding_failure(seconds=2.0)
        logger.warning("legal embedding request failed: %s", exc)
        return [None for _ in texts]

    if len(raw_response) > _MAX_RESPONSE_BYTES:
        mark_embedding_failure(seconds=30.0)
        logger.warning("legal embedding response too large: %s bytes", len(raw_response))
        return [None for _ in texts]

    try:
        data = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        mark_embedding_failure()
        return [None for _ in texts]

    raw_items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        return [None for _ in texts]

    ordered: list[Any] = [None for _ in texts]
    seen: set[int] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(texts) or index in seen:
            return [None for _ in texts]
        seen.add(index)
        ordered[index] = item.get("embedding")
    if len(seen) != len(texts):
        return [None for _ in texts]
    return [_coerce_embedding(item) for item in ordered]


def embed_texts(
    texts: list[str],
    *,
    config: LegalVectorConfig | None = None,
    retries: int = 4,
) -> list[list[float] | None]:
    cfg = config or get_legal_vector_config()
    if not texts:
        return []
    results: list[list[float] | None] = [None for _ in texts]
    batch_size = max(1, cfg.embedding_batch_size)
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors: list[list[float] | None] = [None for _ in batch]
        for attempt in range(max(1, retries)):
            clear_embedding_failure()
            vectors = request_embedding_batch(batch, config=cfg)
            if any(vectors) and all(vectors):
                break
            if any(vectors) and not all(vectors):
                # 部分成功少见；整批重试更稳妥
                pass
            if attempt + 1 < retries:
                time.sleep(min(8.0, 0.5 * (2**attempt)))
        results[start : start + len(batch)] = vectors
    return results


def probe_embedding_dimension(config: LegalVectorConfig | None = None) -> int:
    """实际调用 embedding 接口获取维度，禁止按模型名猜测。"""
    cfg = config or get_legal_vector_config()
    vectors = embed_texts(["法律向量维度探测"], config=cfg, retries=2)
    if not vectors or not vectors[0]:
        raise RuntimeError("无法从 embedding 服务获取向量维度")
    return len(vectors[0])
