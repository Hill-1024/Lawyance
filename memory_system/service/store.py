from __future__ import annotations

import copy
import json
import os
import sqlite3
from contextlib import closing
from typing import Any

from .state import *
from .utils import *
from .errors import MemoryRevisionConflict
from .schema import _blank_snapshot, _sanitize_snapshot, _prune_snapshot, _public_snapshot

def _scope_lock(scope: str) -> threading.RLock:
    with _SCOPE_LOCKS_LOCK:
        lock = _SCOPE_LOCKS.get(scope)
        if lock is None:
            lock = threading.RLock()
            _SCOPE_LOCKS[scope] = lock
        return lock

def _cache_put(scope: str, snapshot: dict[str, Any]) -> None:
    with _CONVERSATION_CACHE_LOCK:
        _CONVERSATION_CACHE[scope] = copy.deepcopy(snapshot)
        _CONVERSATION_CACHE.move_to_end(scope)
        while len(_CONVERSATION_CACHE) > MAX_CONVERSATION_CACHE_SCOPES:
            _CONVERSATION_CACHE.popitem(last=False)

def _cache_remove(scope: str) -> None:
    with _CONVERSATION_CACHE_LOCK:
        _CONVERSATION_CACHE.pop(scope, None)

def _scope_lock_remove(scope: str) -> None:
    with _SCOPE_LOCKS_LOCK:
        _SCOPE_LOCKS.pop(scope, None)

def _ensure_memory_db() -> None:
    if _DB_READY.is_set():
        return
    with _DB_READY_LOCK:
        if _DB_READY.is_set():
            return
        os.makedirs(os.path.dirname(_MEMORY_DB_PATH) or ".", exist_ok=True)
        with closing(sqlite3.connect(_MEMORY_DB_PATH, timeout=5)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_memory (
                    scope TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_memory_last_accessed "
                "ON conversation_memory(last_accessed_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    scope TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY(scope, model, cache_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_embedding_cache_last_used "
                "ON embedding_cache(last_used_at)"
            )
            from . import embeddings

            config = embeddings._embedding_config()
            if config and config.get("model"):
                conn.execute("DELETE FROM embedding_cache WHERE model != ?", (config["model"],))
            conn.commit()
        _DB_READY.set()

def _connect_memory_db() -> sqlite3.Connection:
    _ensure_memory_db()
    conn = sqlite3.connect(_MEMORY_DB_PATH, timeout=5, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _snapshot_from_store_json(raw_json: str | None) -> dict[str, Any]:
    if not raw_json:
        return _blank_snapshot()
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError:
        return _blank_snapshot()
    return _sanitize_snapshot(raw)

def _apply_revision(snapshot: dict[str, Any], revision: int) -> dict[str, Any]:
    snapshot["revision"] = max(0, int(revision))
    return snapshot

def _read_snapshot_from_store(scope: str) -> dict[str, Any]:
    with _scope_lock(scope):
        with closing(_connect_memory_db()) as conn:
            row = conn.execute(
                "SELECT snapshot_json, revision FROM conversation_memory WHERE scope = ?",
                (scope,),
            ).fetchone()
            if not row:
                snapshot = _apply_revision(_blank_snapshot(), 0)
            else:
                snapshot = _snapshot_from_store_json(row[0])
                _apply_revision(snapshot, int(row[1]))
                conn.execute(
                    "UPDATE conversation_memory SET last_accessed_at = ? WHERE scope = ?",
                    (_now_iso(), scope),
                )
        _cache_put(scope, snapshot)
        return copy.deepcopy(snapshot)

def _save_snapshot_in_transaction(
    conn: sqlite3.Connection,
    scope: str,
    snapshot: dict[str, Any],
    revision: int,
) -> None:
    now = _now_iso()
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO conversation_memory(scope, snapshot_json, revision, updated_at, last_accessed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scope) DO UPDATE SET
            snapshot_json = excluded.snapshot_json,
            revision = excluded.revision,
            updated_at = excluded.updated_at,
            last_accessed_at = excluded.last_accessed_at
        """,
        (scope, payload, revision, snapshot.get("updated_at") or now, now),
    )

def _mutate_snapshot(
    scope: str,
    mutator,
    *,
    expected_revision: int | None = None,
    return_mutation_result: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], Any]:
    with _scope_lock(scope):
        with closing(_connect_memory_db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT snapshot_json, revision FROM conversation_memory WHERE scope = ?",
                    (scope,),
                ).fetchone()
                current = _snapshot_from_store_json(row[0] if row else None)
                revision = int(row[1]) if row else 0
                _apply_revision(current, revision)
                if expected_revision is not None and expected_revision != revision:
                    raise MemoryRevisionConflict(expected_revision, revision, _public_snapshot(current))
                mutated = mutator(current)
                mutation_result = None
                if isinstance(mutated, tuple) and len(mutated) == 2:
                    updated, mutation_result = mutated
                else:
                    updated = mutated
                updated = _prune_snapshot(updated)
                new_revision = revision + 1
                _apply_revision(updated, new_revision)
                updated["last_synced_at"] = _now_iso()
                _save_snapshot_in_transaction(conn, scope, updated, new_revision)
                conn.execute("COMMIT")
            except MemoryRevisionConflict:
                conn.execute("ROLLBACK")
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise
        _cache_put(scope, updated)
        if return_mutation_result:
            return copy.deepcopy(updated), copy.deepcopy(mutation_result)
        return copy.deepcopy(updated)

__all__ = [name for name in globals() if not name.startswith("__")]
