from __future__ import annotations

import json
import sqlite3
import struct
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from contextlib import closing
from typing import Any

from .state import *
from .utils import *

def _embedding_config() -> dict[str, Any] | None:
    if time.time() < _EMBEDDING_FAILURE_UNTIL:
        return None
    return _EMBEDDING_CONFIG

def _embedding_text(text: Any) -> str:
    return _clip(text, MAX_EMBEDDING_TEXT_CHARS)

def _embedding_cache_key(model: str, text: str) -> str:
    return _stable_id("emb", model, text)

def _embedding_scope(scope: str | None) -> str:
    return scope or EMBEDDING_SCOPE_GLOBAL

def _pack_embedding(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *[float(value) for value in vector])

def _unpack_embedding(blob: bytes, dim: int) -> list[float] | None:
    if not blob or dim <= 0 or len(blob) != dim * 4:
        return None
    try:
        return list(struct.unpack(f"<{dim}f", blob))
    except struct.error:
        return None

def _embedding_cache_total_locked() -> int:
    return sum(len(bucket) for bucket in _EMBEDDING_CACHE.values())

def _trim_embedding_cache_locked() -> None:
    for bucket in _EMBEDDING_CACHE.values():
        while len(bucket) > MAX_EMBEDDING_CACHE_ITEMS_PER_SCOPE:
            bucket.popitem(last=False)

    while _embedding_cache_total_locked() > MAX_EMBEDDING_CACHE_ITEMS:
        victim_scope = next(
            (
                scope
                for scope, bucket in _EMBEDDING_CACHE.items()
                if bucket and len(bucket) > MIN_EMBEDDING_CACHE_ITEMS_PER_SCOPE
            ),
            None,
        )
        if victim_scope is None:
            victim_scope = max(_EMBEDDING_CACHE, key=lambda key: len(_EMBEDDING_CACHE[key]), default=None)
            if victim_scope is None or not _EMBEDDING_CACHE[victim_scope]:
                break
        _EMBEDDING_CACHE[victim_scope].popitem(last=False)
        if not _EMBEDDING_CACHE[victim_scope]:
            _EMBEDDING_CACHE.pop(victim_scope, None)

def _load_embedding_scope_cache(scope: str, model: str) -> None:
    loaded_key = (scope, model)
    if loaded_key in _EMBEDDING_LOADED_SCOPES:
        return
    from .store import _connect_memory_db

    try:
        with closing(_connect_memory_db()) as conn:
            rows = conn.execute(
                """
                SELECT cache_key, dim, vector_blob
                FROM embedding_cache
                WHERE scope = ? AND model = ?
                ORDER BY last_used_at DESC
                LIMIT ?
                """,
                (scope, model, MAX_EMBEDDING_CACHE_ITEMS_PER_SCOPE),
            ).fetchall()
    except sqlite3.Error as exc:
        _LOGGER.warning("embedding cache load failed: %s", _clip(exc, 120))
        return
    _EMBEDDING_LOADED_SCOPES.add(loaded_key)
    bucket = _EMBEDDING_CACHE.setdefault(scope, OrderedDict())
    for cache_key, dim, vector_blob in reversed(rows):
        vector = _unpack_embedding(vector_blob, int(dim))
        if vector is None:
            continue
        bucket[str(cache_key)] = vector
        bucket.move_to_end(str(cache_key))
    _EMBEDDING_CACHE.move_to_end(scope)
    _trim_embedding_cache_locked()

def _persist_embedding_cache_entry(scope: str, model: str, key: str, vector: list[float]) -> None:
    try:
        blob = _pack_embedding(vector)
        from .store import _connect_memory_db

        with closing(_connect_memory_db()) as conn:
            conn.execute(
                """
                INSERT INTO embedding_cache(scope, model, cache_key, dim, vector_blob, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, model, cache_key) DO UPDATE SET
                    dim = excluded.dim,
                    vector_blob = excluded.vector_blob,
                    last_used_at = excluded.last_used_at
                """,
                (scope, model, key, len(vector), blob, _now_iso()),
            )
    except (sqlite3.Error, struct.error, ValueError) as exc:
        _LOGGER.warning("embedding cache persist failed: %s", _clip(exc, 120))

def _embedding_cache_get(scope: str | None, model: str, key: str) -> list[float] | None:
    resolved_scope = _embedding_scope(scope)
    with _EMBEDDING_LOCK:
        _load_embedding_scope_cache(resolved_scope, model)
        bucket = _EMBEDDING_CACHE.get(resolved_scope)
        vector = bucket.get(key) if bucket else None
        if vector is not None:
            bucket.move_to_end(key)
            _EMBEDDING_CACHE.move_to_end(resolved_scope)
            return list(vector)
    return None

def _embedding_cache_set(scope: str | None, model: str, key: str, vector: list[float]) -> None:
    resolved_scope = _embedding_scope(scope)
    with _EMBEDDING_LOCK:
        _load_embedding_scope_cache(resolved_scope, model)
        bucket = _EMBEDDING_CACHE.setdefault(resolved_scope, OrderedDict())
        bucket[key] = list(vector)
        bucket.move_to_end(key)
        _EMBEDDING_CACHE.move_to_end(resolved_scope)
        _trim_embedding_cache_locked()
    _persist_embedding_cache_entry(resolved_scope, model, key, vector)

def _coerce_embedding(raw_embedding: Any) -> list[float] | None:
    if not isinstance(raw_embedding, list) or not raw_embedding:
        return None
    try:
        vector = [float(value) for value in raw_embedding]
    except (TypeError, ValueError):
        return None
    if not any(vector):
        return None
    return vector

def _request_embedding_batch(config: dict[str, Any], texts: list[str]) -> list[list[float] | None]:
    payload = json.dumps(
        {
            "model": config["model"],
            "input": texts,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config['base_url']}/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=float(config.get("timeout", 8))) as response:
        raw_response = response.read(EMBEDDING_MAX_RESPONSE_BYTES + 1)
    if len(raw_response) > EMBEDDING_MAX_RESPONSE_BYTES:
        raise ValueError("embedding response too large")
    data = json.loads(raw_response.decode("utf-8"))

    raw_items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        return [None for _ in texts]

    ordered: list[Any] = [None for _ in texts]
    seen_indexes: set[int] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(texts) or index in seen_indexes:
            return [None for _ in texts]
        seen_indexes.add(index)
        ordered[index] = item.get("embedding")
    if len(seen_indexes) != len(texts):
        return [None for _ in texts]
    return [_coerce_embedding(item) for item in ordered]

def _embedding_vectors_for_ranking(
    query_text: str,
    item_texts: list[str],
    scope: str | None = None,
) -> tuple[list[float] | None, dict[str, list[float]]]:
    config = _embedding_config()
    if not config or not query_text.strip():
        return None, {}

    global _EMBEDDING_FAILURE_UNTIL
    texts: list[str] = []
    seen = set()
    for text in [_embedding_text(query_text), *(_embedding_text(item) for item in item_texts)]:
        if not text:
            continue
        key = _embedding_cache_key(config["model"], text)
        if key in seen:
            continue
        seen.add(key)
        texts.append(text)

    missing = [
        text
        for text in texts
        if _embedding_cache_get(scope, config["model"], _embedding_cache_key(config["model"], text)) is None
    ]
    try:
        for start in range(0, len(missing), MAX_EMBEDDING_BATCH_SIZE):
            batch = missing[start : start + MAX_EMBEDDING_BATCH_SIZE]
            vectors: list[list[float] | None] = []
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    vectors = _request_embedding_batch(config, batch)
                    last_exc = None
                    break
                except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
                    last_exc = exc
                    if attempt == 0:
                        retry_delay = float(config.get("retry_delay", 0.5) or 0)
                        if retry_delay > 0:
                            time.sleep(retry_delay)
            if last_exc is not None:
                raise last_exc
            for text, vector in zip(batch, vectors):
                if vector:
                    _embedding_cache_set(scope, config["model"], _embedding_cache_key(config["model"], text), vector)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        _EMBEDDING_FAILURE_UNTIL = time.time() + 60
        _LOGGER.warning("embedding disabled temporarily: %s: %s", type(exc).__name__, _clip(exc, 120))
        return None, {}

    query_key = _embedding_cache_key(config["model"], _embedding_text(query_text))
    item_vectors = {
        _embedding_text(text): vector
        for text in item_texts
        for key in [_embedding_cache_key(config["model"], _embedding_text(text))]
        for vector in [_embedding_cache_get(scope, config["model"], key)]
        if _embedding_text(text) and vector is not None
    }
    return _embedding_cache_get(scope, config["model"], query_key), item_vectors

__all__ = [name for name in globals() if not name.startswith("__")]
