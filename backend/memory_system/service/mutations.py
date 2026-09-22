from __future__ import annotations

import copy
import time
from typing import Any

from .state import *
from .utils import *
from .schema import _public_snapshot
from .extraction import *
from .store import _mutate_snapshot

def _find_memory_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("id") == item_id:
            return item
    return None

def _memory_edit_reason(operation: dict[str, Any]) -> tuple[str, str | None]:
    reason = operation.get("reason")
    if reason not in MEMORY_EDIT_REASONS:
        return "", "invalid_reason"
    return str(reason), None

def _memory_edit_priority(value: Any, default: float) -> float:
    try:
        return _clamp(float(value))
    except (TypeError, ValueError):
        return default

def _memory_source_text(operation: dict[str, Any]) -> tuple[str, str | None]:
    source_text = _clip(operation.get("source_text") or "", 500)
    if not source_text:
        return "", "missing_source_text"
    return source_text, None

def _build_model_fact(operation: dict[str, Any], *, source_text: str, reason: str, supersedes: str | None = None) -> dict[str, Any]:
    now = _now_iso()
    text = _clip(operation.get("text") or operation.get("new_text") or "", MAX_FACT_TEXT_CHARS)
    kind = str(operation.get("kind") or "fact")
    if kind not in MEMORY_FACT_KINDS:
        kind = "fact"
    fact = {
        "id": str(operation.get("id") or _stable_id("mem", "model", kind, _normalized(text), time.time_ns())),
        "kind": kind,
        "text": text,
        "status": "active",
        "priority": _memory_edit_priority(operation.get("priority"), 0.76 if kind == "fact" else 0.82),
        "confidence": _memory_edit_priority(operation.get("confidence"), 0.78),
        "source_event_ids": [],
        "source_text": source_text,
        "memory_reason": reason,
        "created_at": now,
        "updated_at": now,
        "keywords": _extract_keywords(text),
        "entities": _extract_entities(text),
        "semantic_tags": _semantic_tags(text),
    }
    if operation.get("source_turn_id"):
        fact["source_turn_id"] = str(operation["source_turn_id"])
    if operation.get("fact_key"):
        fact["fact_key"] = str(operation["fact_key"])
    if supersedes:
        fact["supersedes"] = supersedes
    return fact

def _memory_accept(op_index: int, operation: dict[str, Any], **extra) -> dict[str, Any]:
    payload = {
        "op_index": op_index,
        "op": operation.get("op"),
        "auto_deprecated_ids": [],
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload

def _deprecate_fact(
    fact: dict[str, Any],
    *,
    superseded_by: str | None = None,
    source_text: str | None = None,
    reason: str | None = None,
) -> None:
    fact["status"] = "deprecated"
    fact["updated_at"] = _now_iso()
    if superseded_by:
        fact["superseded_by"] = superseded_by
    if source_text:
        fact["source_text"] = source_text
    if reason:
        fact["memory_reason"] = reason

def _apply_memory_create_fact(snapshot: dict[str, Any], operation: dict[str, Any], op_index: int = 0) -> tuple[dict[str, Any] | None, str | None]:
    reason, error = _memory_edit_reason(operation)
    if error:
        return None, error
    source_text, error = _memory_source_text(operation)
    if error:
        return None, error
    text = _clip(operation.get("text") or "", MAX_FACT_TEXT_CHARS)
    if not text:
        return None, "missing_text"
    fact = _build_model_fact(operation, source_text=source_text, reason=reason)
    if not fact.get("fact_key"):
        fact_key = _fact_key_for_text(
            fact["text"],
            fact.get("kind", "fact"),
            fact.get("entities", []),
            fact.get("semantic_tags", []),
            _active_case_focus_id(snapshot),
        )
        if fact_key:
            fact["fact_key"] = fact_key
    auto_deprecated_ids = _mark_conflicts(snapshot, fact)
    stored = _append_unique(snapshot["facts"], fact, similar_threshold=1.01)
    return _memory_accept(
        op_index,
        operation,
        created_id=stored.get("id"),
        auto_deprecated_ids=auto_deprecated_ids,
    ), None

def _apply_memory_update_fact(snapshot: dict[str, Any], operation: dict[str, Any], op_index: int = 0) -> tuple[dict[str, Any] | None, str | None]:
    reason, error = _memory_edit_reason(operation)
    if error:
        return None, error
    source_text, error = _memory_source_text(operation)
    if error:
        return None, error
    target = _find_memory_item(snapshot.get("facts", []), str(operation.get("target_id") or ""))
    if not target:
        return None, "unknown_target_fact"
    if target.get("status") != "active":
        return None, "target_fact_not_active"
    new_text = _clip(operation.get("new_text") or operation.get("text") or "", MAX_FACT_TEXT_CHARS)
    if not new_text:
        return None, "missing_new_text"
    replacement_operation = dict(operation)
    replacement_operation["text"] = new_text
    replacement_operation["kind"] = operation.get("kind") or target.get("kind") or "fact"
    replacement_operation["fact_key"] = operation.get("fact_key") or target.get("fact_key")
    fact = _build_model_fact(replacement_operation, source_text=source_text, reason=reason, supersedes=target["id"])
    auto_deprecated_ids: list[str] = []
    target_key = target.get("fact_key")
    for candidate in snapshot.get("facts", []):
        if candidate.get("status") != "active":
            continue
        if candidate.get("id") == target.get("id") or (target_key and candidate.get("fact_key") == target_key):
            _deprecate_fact(candidate, superseded_by=fact["id"], reason=reason)
            auto_deprecated_ids.append(str(candidate.get("id")))
    for deprecated_id in _mark_conflicts(snapshot, fact):
        if deprecated_id not in auto_deprecated_ids:
            auto_deprecated_ids.append(deprecated_id)
    stored = _append_unique(snapshot["facts"], fact, similar_threshold=1.01)
    return _memory_accept(
        op_index,
        operation,
        updated_id=stored.get("id"),
        deprecated_id=target.get("id"),
        auto_deprecated_ids=auto_deprecated_ids,
    ), None

def _apply_memory_deprecate_fact(snapshot: dict[str, Any], operation: dict[str, Any], op_index: int = 0) -> tuple[dict[str, Any] | None, str | None]:
    reason, error = _memory_edit_reason(operation)
    if error:
        return None, error
    source_text, error = _memory_source_text(operation)
    if error:
        return None, error
    target = _find_memory_item(snapshot.get("facts", []), str(operation.get("target_id") or ""))
    if not target:
        return None, "unknown_target_fact"
    _deprecate_fact(target, source_text=source_text, reason=reason)
    return _memory_accept(op_index, operation, deprecated_id=target.get("id")), None

def _apply_memory_deprecate_focus(snapshot: dict[str, Any], operation: dict[str, Any], op_index: int = 0) -> tuple[dict[str, Any] | None, str | None]:
    reason, error = _memory_edit_reason(operation)
    if error:
        return None, error
    source_text, error = _memory_source_text(operation)
    if error:
        return None, error
    target = _find_memory_item(snapshot.get("focus", []), str(operation.get("target_id") or ""))
    if not target:
        return None, "unknown_target_focus"
    target["status"] = "deprecated"
    target["updated_at"] = _now_iso()
    target["source_text"] = source_text
    target["memory_reason"] = reason
    return _memory_accept(op_index, operation, deprecated_id=target.get("id")), None

def _apply_memory_update_focus(snapshot: dict[str, Any], operation: dict[str, Any], op_index: int = 0) -> tuple[dict[str, Any] | None, str | None]:
    reason, error = _memory_edit_reason(operation)
    if error:
        return None, error
    source_text, error = _memory_source_text(operation)
    if error:
        return None, error
    text = _clip(operation.get("text") or "", MAX_FACT_TEXT_CHARS)
    if not text:
        return None, "missing_text"
    target_id = str(operation.get("target_id") or "")
    target = _find_memory_item(snapshot.get("focus", []), target_id) if target_id else None
    now = _now_iso()
    focus_payload = {
        "id": target.get("id") if target else str(operation.get("id") or _stable_id("focus", _normalized(text))),
        "text": text,
        "status": "active",
        "priority": _memory_edit_priority(operation.get("priority"), 0.76),
        "focus_type": operation.get("focus_type") if operation.get("focus_type") in {"case", "dialog"} else _infer_focus_type(text),
        "source_text": source_text,
        "memory_reason": reason,
        "created_at": target.get("created_at") if target else now,
        "updated_at": now,
        "keywords": _extract_keywords(text),
        "entities": _extract_entities(text),
        "semantic_tags": _semantic_tags(text),
    }
    if target:
        target.update(focus_payload)
        stored = target
    else:
        stored = _append_unique(snapshot["focus"], focus_payload, similar_threshold=0.86)
    return _memory_accept(op_index, operation, updated_id=stored.get("id")), None

def update_conversation_memory(scope: str, operations: Any) -> dict[str, Any]:
    if not isinstance(operations, list):
        operations = []
    requested_count = len(operations)
    executable_operations = operations[:MAX_MEMORY_OPS_PER_CALL]
    rejected: list[dict[str, Any]] = [
        {"index": index, "op": operation.get("op") if isinstance(operation, dict) else None, "error": "too_many_ops"}
        for index, operation in enumerate(operations[MAX_MEMORY_OPS_PER_CALL:], start=MAX_MEMORY_OPS_PER_CALL)
    ]
    handlers = {
        "create_fact": _apply_memory_create_fact,
        "update_fact": _apply_memory_update_fact,
        "deprecate_fact": _apply_memory_deprecate_fact,
        "deprecate_focus": _apply_memory_deprecate_focus,
        "update_focus": _apply_memory_update_focus,
    }

    def mutate(current: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot = copy.deepcopy(current)
        accepted: list[dict[str, Any]] = []
        local_rejected: list[dict[str, Any]] = []
        for index, operation in enumerate(executable_operations):
            if not isinstance(operation, dict):
                local_rejected.append({"index": index, "error": "invalid_operation"})
                continue
            op_name = operation.get("op")
            handler = handlers.get(op_name)
            if not handler:
                local_rejected.append({"index": index, "op": op_name, "error": "unknown_operation"})
                continue
            accepted_item, error = handler(snapshot, operation, index)
            if accepted_item:
                accepted.append(accepted_item)
            else:
                local_rejected.append({"index": index, "op": op_name, "error": error or "rejected"})
        snapshot["updated_at"] = _now_iso()
        return snapshot, {"accepted": accepted, "rejected": local_rejected}

    snapshot, mutation_result = _mutate_snapshot(scope, mutate, return_mutation_result=True)
    accepted_items = (mutation_result or {}).get("accepted", [])
    rejected_items = (mutation_result or {}).get("rejected", []) + rejected
    _LOGGER.info(
        "model_memory_update scope=%s operations=%s accepted=%s rejected=%s",
        scope,
        requested_count,
        len(accepted_items),
        len(rejected_items),
    )
    return {
        "status": "success",
        "accepted": accepted_items,
        "accepted_count": len(accepted_items),
        "rejected": rejected_items,
        "rejected_count": len(rejected_items),
        "memory": _public_snapshot(snapshot),
    }

__all__ = [name for name in globals() if not name.startswith("__")]
