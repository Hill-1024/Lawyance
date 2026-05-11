from __future__ import annotations

import copy
from typing import Any

from .state import *
from .utils import *

def _blank_snapshot() -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": MEMORY_VERSION,
        "revision": 0,
        "scope": {
            "type": "conversation",
            "future_user_scope": None,
        },
        "events": [],
        "facts": [],
        "focus": [],
        "updated_at": now,
        "last_synced_at": now,
    }

def _sanitize_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    role = raw.get("role")
    if role not in {"user", "assistant", "system"}:
        return None
    content = _strip_message_noise(raw.get("content") or raw.get("summary") or "")
    if not content:
        return None
    created_at = raw.get("created_at") if isinstance(raw.get("created_at"), str) else _now_iso()
    event = {
        "id": str(raw.get("id") or _stable_id("evt", role, content)),
        "type": str(raw.get("type") or "message"),
        "role": role,
        "content": content,
        "summary": _clip(raw.get("summary") or content, 360),
        "keywords": _sanitize_keywords(raw.get("keywords"), content),
        "entities": _sanitize_entities(raw.get("entities"), content),
        "semantic_tags": _sanitize_semantic_tags(raw.get("semantic_tags"), content),
        "created_at": created_at,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else created_at,
    }
    if raw.get("turn_id"):
        event["turn_id"] = str(raw["turn_id"])
    return event

def _sanitize_fact(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = _clip(raw.get("text") or raw.get("content") or "", MAX_FACT_TEXT_CHARS)
    if not text:
        return None
    now = _now_iso()
    kind = str(raw.get("kind") or "fact")
    if kind not in MEMORY_FACT_KINDS:
        kind = "fact"
    status = str(raw.get("status") or "active")
    if status not in {"active", "deprecated"}:
        status = "active"
    source_event_ids = raw.get("source_event_ids")
    if not isinstance(source_event_ids, list):
        source_event_ids = []
    fact = {
        "id": str(raw.get("id") or _stable_id("mem", kind, text)),
        "kind": kind,
        "text": text,
        "status": status,
        "priority": _clamp(raw.get("priority", 0.5) or 0.5),
        "confidence": _clamp(raw.get("confidence", 0.75) or 0.75),
        "source_event_ids": [str(item) for item in source_event_ids[:8]],
        "created_at": raw.get("created_at") if isinstance(raw.get("created_at"), str) else now,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else now,
        "keywords": _sanitize_keywords(raw.get("keywords"), text),
        "entities": _sanitize_entities(raw.get("entities"), text),
        "semantic_tags": _sanitize_semantic_tags(raw.get("semantic_tags"), text),
    }
    if raw.get("fact_key"):
        fact["fact_key"] = str(raw["fact_key"])
    if raw.get("source_text"):
        fact["source_text"] = _clip(raw["source_text"], 360)
    if raw.get("source_turn_id"):
        fact["source_turn_id"] = str(raw["source_turn_id"])
    if raw.get("memory_reason") in MEMORY_EDIT_REASONS:
        fact["memory_reason"] = raw["memory_reason"]
    if raw.get("superseded_by"):
        fact["superseded_by"] = str(raw["superseded_by"])
    if raw.get("supersedes"):
        fact["supersedes"] = str(raw["supersedes"])
    return fact

def _sanitize_focus(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = _clip(raw.get("text") or raw.get("content") or "", MAX_FACT_TEXT_CHARS)
    if not text:
        return None
    now = _now_iso()
    status = str(raw.get("status") or "active")
    if status not in {"active", "deprecated"}:
        status = "active"
    focus = {
        "id": str(raw.get("id") or _stable_id("focus", text)),
        "text": text,
        "status": status,
        "priority": _clamp(raw.get("priority", 0.6) or 0.6),
        "created_at": raw.get("created_at") if isinstance(raw.get("created_at"), str) else now,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else now,
        "keywords": _sanitize_keywords(raw.get("keywords"), text),
        "entities": _sanitize_entities(raw.get("entities"), text),
        "semantic_tags": _sanitize_semantic_tags(raw.get("semantic_tags"), text),
    }
    if raw.get("focus_type") in {"case", "dialog"}:
        focus["focus_type"] = raw["focus_type"]
    if raw.get("source_text"):
        focus["source_text"] = _clip(raw["source_text"], 360)
    if raw.get("memory_reason") in MEMORY_EDIT_REASONS:
        focus["memory_reason"] = raw["memory_reason"]
    if raw.get("last_accessed_at") and isinstance(raw.get("last_accessed_at"), str):
        focus["last_accessed_at"] = raw["last_accessed_at"]
    return focus

def _sanitize_snapshot(snapshot: Any) -> dict[str, Any]:
    clean = _blank_snapshot()
    if not isinstance(snapshot, dict):
        return clean

    scope = snapshot.get("scope")
    if isinstance(scope, dict):
        clean["scope"] = {
            "type": "conversation",
            "future_user_scope": scope.get("future_user_scope"),
        }
    if snapshot.get("conversation_id"):
        clean["conversation_id"] = str(snapshot["conversation_id"])
    try:
        clean["revision"] = max(0, int(snapshot.get("revision", 0) or 0))
    except (TypeError, ValueError):
        clean["revision"] = 0

    raw_events = snapshot.get("events") if isinstance(snapshot.get("events"), list) else []
    raw_facts = snapshot.get("facts") if isinstance(snapshot.get("facts"), list) else []
    raw_focus = snapshot.get("focus") if isinstance(snapshot.get("focus"), list) else []
    events = [_sanitize_event(item) for item in raw_events]
    facts = [_sanitize_fact(item) for item in raw_facts]
    focus = [_sanitize_focus(item) for item in raw_focus]
    clean["events"] = [item for item in events if item]
    clean["facts"] = [item for item in facts if item]
    clean["focus"] = [item for item in focus if item]
    clean["updated_at"] = snapshot.get("updated_at") if isinstance(snapshot.get("updated_at"), str) else clean["updated_at"]
    clean["last_synced_at"] = snapshot.get("last_synced_at") if isinstance(snapshot.get("last_synced_at"), str) else clean["last_synced_at"]
    return _prune_snapshot(clean)

def _prefer_newer(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if _timestamp(incoming.get("updated_at")) >= _timestamp(existing.get("updated_at")):
        return incoming
    return existing

def _merge_items(base_items: list[dict[str, Any]], incoming_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in base_items + incoming_items:
        item_id = str(item.get("id") or _stable_id("item", item.get("text") or item.get("content") or ""))
        if item_id in merged:
            merged[item_id] = _prefer_newer(merged[item_id], item)
        else:
            merged[item_id] = item
    return list(merged.values())

def _merge_snapshots(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base or _blank_snapshot())
    incoming = incoming or _blank_snapshot()
    result["version"] = MEMORY_VERSION
    if incoming.get("conversation_id"):
        result["conversation_id"] = incoming["conversation_id"]
    result["scope"] = {
        "type": "conversation",
        "future_user_scope": incoming.get("scope", {}).get("future_user_scope"),
    }
    result["events"] = _merge_items(result.get("events", []), incoming.get("events", []))
    result["facts"] = _merge_items(result.get("facts", []), incoming.get("facts", []))
    result["focus"] = _merge_items(result.get("focus", []), incoming.get("focus", []))
    result["updated_at"] = max(
        result.get("updated_at") or "",
        incoming.get("updated_at") or "",
    )
    result["last_synced_at"] = _now_iso()
    return _prune_snapshot(result)

def _snapshot_shell_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = _blank_snapshot()
    if snapshot.get("conversation_id"):
        result["conversation_id"] = snapshot["conversation_id"]
    result["scope"] = {
        "type": "conversation",
        "future_user_scope": snapshot.get("scope", {}).get("future_user_scope"),
    }
    return result

def _prune_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot["events"] = sorted(
        snapshot.get("events", []),
        key=lambda item: (_timestamp(item.get("updated_at")), _timestamp(item.get("created_at"))),
        reverse=True,
    )[:MAX_EVENTS]
    snapshot["facts"] = sorted(
        snapshot.get("facts", []),
        key=lambda item: (item.get("status") == "active", float(item.get("priority", 0)), _timestamp(item.get("updated_at"))),
        reverse=True,
    )[:MAX_FACTS]
    snapshot["focus"] = sorted(
        snapshot.get("focus", []),
        key=lambda item: (
            item.get("status") != "deprecated",
            _clamp(item.get("priority", 0)),
            _timestamp(item.get("updated_at")),
        ),
        reverse=True,
    )[:MAX_FOCUS]
    snapshot["version"] = MEMORY_VERSION
    return snapshot

def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    clean = _prune_snapshot(copy.deepcopy(snapshot))
    clean["last_synced_at"] = _now_iso()
    return clean

def _memory_fact_view(fact: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": fact.get("id"),
        "kind": fact.get("kind"),
        "text": fact.get("text"),
        "status": fact.get("status"),
        "priority": fact.get("priority"),
        "confidence": fact.get("confidence"),
        "updated_at": fact.get("updated_at"),
        "source_event_ids": fact.get("source_event_ids", []),
    }
    for key in ("fact_key", "superseded_by", "supersedes", "source_text", "source_turn_id", "memory_reason"):
        if fact.get(key):
            result[key] = fact[key]
    return result

def _memory_focus_view(focus: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": focus.get("id"),
        "text": focus.get("text"),
        "status": focus.get("status"),
        "priority": focus.get("priority"),
        "focus_type": focus.get("focus_type"),
        "updated_at": focus.get("updated_at"),
    }
    for key in ("source_text", "memory_reason"):
        if focus.get(key):
            result[key] = focus[key]
    return result

def _memory_event_view(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "role": event.get("role"),
        "summary": event.get("summary"),
        "turn_id": event.get("turn_id"),
        "updated_at": event.get("updated_at"),
    }

def _memory_meta(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": snapshot.get("version", MEMORY_VERSION),
        "revision": snapshot.get("revision", 0),
        "updated_at": snapshot.get("updated_at"),
        "last_synced_at": snapshot.get("last_synced_at"),
        "events": len(snapshot.get("events", [])),
        "facts": len(snapshot.get("facts", [])),
        "focus": len(snapshot.get("focus", [])),
    }

__all__ = [name for name in globals() if not name.startswith("__")]
