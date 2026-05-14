from __future__ import annotations

import time
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from .state import *
from .utils import *
from .schema import *
from .extraction import _observe_messages
from .store import *
from .ranking import _build_context_packet, _rank_items, _touch_retrieved_focus
from .mutations import update_conversation_memory

def inspect_conversation_memory(
    scope: str,
    query: str = "",
    include_deprecated: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    snapshot = _read_snapshot_from_store(scope)
    try:
        resolved_limit = max(1, min(int(limit), 40))
    except (TypeError, ValueError):
        resolved_limit = 20
    facts = [
        fact
        for fact in snapshot.get("facts", [])
        if include_deprecated or fact.get("status") == "active"
    ][:resolved_limit]
    focus = [
        item
        for item in snapshot.get("focus", [])
        if include_deprecated or item.get("status") != "deprecated"
    ][:12]
    events = snapshot.get("events", [])[:12]
    retrieved, ranking = _rank_items(snapshot, query or "", min(resolved_limit, 12), scope) if query else ([], {})
    return {
        "status": "success",
        "facts": [_memory_fact_view(fact) for fact in facts],
        "focus": [_memory_focus_view(item) for item in focus],
        "recent_events": [_memory_event_view(event) for event in events],
        "related_items": retrieved,
        "rag": ranking,
        "memory_meta": _memory_meta(snapshot),
    }

def sync_conversation_memory(
    scope: str,
    snapshot: Any = None,
    messages: list[dict[str, Any]] | None = None,
    mode: str | None = None,
    expected_revision: int | None = None,
    memory_conflict_strategy: str | None = None,
) -> dict[str, Any]:
    incoming = _sanitize_snapshot(snapshot)
    sync_mode = mode if mode in {"merge", "rebuild"} else ("rebuild" if messages is not None else "merge")
    has_messages = bool(messages)
    has_incoming_items = bool(incoming.get("events") or incoming.get("facts") or incoming.get("focus"))

    if sync_mode == "merge" and not has_messages and not has_incoming_items:
        current = _read_snapshot_from_store(scope)
        return {"status": "success", "memory": _public_snapshot(current)}

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        if sync_mode == "rebuild":
            merged = _snapshot_shell_from_snapshot(incoming)
            if messages:
                merged = _observe_messages(merged, messages)
            return merged
        merged = _merge_snapshots(current, incoming)
        if messages:
            merged = _observe_messages(merged, messages)
        return merged

    cas_revision = expected_revision if memory_conflict_strategy != "server_merge" else None
    merged = _mutate_snapshot(scope, mutate, expected_revision=cas_revision)
    _LOGGER.info(
        "sync scope=%s mode=%s messages=%s events=%s facts=%s focus=%s",
        scope,
        sync_mode,
        len(messages) if messages is not None else "none",
        len(merged.get("events", [])),
        len(merged.get("facts", [])),
        len(merged.get("focus", [])),
    )
    return {
        "status": "success",
        "memory": _public_snapshot(merged),
    }

def retrieve_conversation_memory(scope: str, query: str, limit: int = 8) -> dict[str, Any]:
    snapshot = _read_snapshot_from_store(scope)
    try:
        resolved_limit = max(1, min(int(limit), 12))
    except (TypeError, ValueError):
        resolved_limit = 8
    retrieved, ranking = _rank_items(snapshot, query or "", resolved_limit, scope)
    _touch_retrieved_focus(scope, retrieved)
    context = _build_context_packet(snapshot, query or "", retrieved, resolved_limit)
    routes = sorted({route for item in retrieved for route in item.get("routes", [])})
    _LOGGER.info(
        "retrieve scope=%s query=%s items=%s rag_profile=%s routes=%s",
        scope,
        _clip(_strip_message_noise(query or ""), 80),
        len(retrieved),
        ranking["profile"],
        ",".join(routes) if routes else "none",
    )
    return {
        "status": "success",
        "context": context,
        "items": retrieved,
        "rag": ranking,
        "memory_meta": _memory_meta(snapshot),
    }

def remember_conversation_turn(scope: str, user_message: str, assistant_message: str, turn_id: str | None = None) -> dict[str, Any]:
    resolved_turn_id = turn_id or _stable_id("turn", time.time(), user_message[:120])

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        return _observe_messages(
            current,
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ],
            turn_id=resolved_turn_id,
        )

    snapshot = _mutate_snapshot(scope, mutate)
    _LOGGER.info(
        "remember scope=%s events=%s facts=%s focus=%s",
        scope,
        len(snapshot.get("events", [])),
        len(snapshot.get("facts", [])),
        len(snapshot.get("focus", [])),
    )
    retrieved, _ = _rank_items(snapshot, user_message or "", 8, scope)
    return {
        "status": "success",
        "memory": _public_snapshot(snapshot),
        "context": _build_context_packet(snapshot, user_message or "", retrieved, 8),
    }

def clear_conversation_memory(scope: str) -> dict[str, Any]:
    with _scope_lock(scope):
        with closing(_connect_memory_db()) as conn:
            conn.execute("DELETE FROM conversation_memory WHERE scope = ?", (scope,))
    _cache_remove(scope)
    _scope_lock_remove(scope)
    return {"status": "success"}

def prune_conversation_memory(max_age_seconds: int | None = None) -> dict[str, Any]:
    cutoff_seconds = MEMORY_CACHE_TTL_SECONDS if max_age_seconds is None else max(0, int(max_age_seconds))
    cutoff = datetime.fromtimestamp(time.time() - cutoff_seconds, timezone.utc).isoformat(timespec="seconds")
    with closing(_connect_memory_db()) as conn:
        rows = conn.execute(
            "SELECT scope FROM conversation_memory WHERE last_accessed_at < ?",
            (cutoff,),
        ).fetchall()
        scopes = [row[0] for row in rows]
        conn.executemany("DELETE FROM conversation_memory WHERE scope = ?", [(scope,) for scope in scopes])
    for scope in scopes:
        _cache_remove(scope)
        _scope_lock_remove(scope)
    return {"status": "success", "cleared": len(scopes)}

__all__ = [name for name in globals() if not name.startswith("__")]
