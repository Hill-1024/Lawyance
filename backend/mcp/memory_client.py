"""
模块描述：对话级记忆工具适配器，将 mcps 工具调用转换为 memory_system 的同步、检索和清理操作。
"""

import json
from contextvars import ContextVar
from typing import Any

from memory_system import (
    clear_conversation_memory as clear_cached_memory,
    inspect_conversation_memory as inspect_memory,
    remember_conversation_turn as remember_turn,
    retrieve_conversation_memory as retrieve_memory,
    sync_conversation_memory as sync_memory,
    update_conversation_memory as update_memory,
)


_CURRENT_MEMORY_TURN_ID: ContextVar[str | None] = ContextVar("current_memory_turn_id", default=None)


def set_current_memory_turn_id(turn_id: str | None):
    return _CURRENT_MEMORY_TURN_ID.set(turn_id)


def reset_current_memory_turn_id(token) -> None:
    _CURRENT_MEMORY_TURN_ID.reset(token)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def sync_conversation_memory(
    workspace_scope: str | None,
    snapshot: Any = None,
    messages: list[dict] | None = None,
    mode: str | None = None,
    expected_revision: int | None = None,
    memory_conflict_strategy: str | None = None,
) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    return _dump(
        sync_memory(
            workspace_scope,
            snapshot=snapshot,
            messages=messages,
            mode=mode,
            expected_revision=expected_revision,
            memory_conflict_strategy=memory_conflict_strategy,
        )
    )


def retrieve_conversation_memory(workspace_scope: str | None, query: str, limit: int = 8) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope", "context": "", "items": []})
    return _dump(retrieve_memory(workspace_scope, query=query, limit=limit))


def inspect_conversation_memory(
    workspace_scope: str | None,
    query: str = "",
    include_deprecated: bool = False,
    limit: int = 20,
) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope", "facts": [], "focus": []})
    return _dump(
        inspect_memory(
            workspace_scope,
            query=query,
            include_deprecated=include_deprecated,
            limit=limit,
        )
    )


def update_conversation_memory(workspace_scope: str | None, operations: list[dict] | None = None) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    turn_id = _CURRENT_MEMORY_TURN_ID.get()
    resolved_operations = []
    for operation in operations or []:
        if isinstance(operation, dict) and turn_id and not operation.get("source_turn_id"):
            operation = {**operation, "source_turn_id": turn_id}
        resolved_operations.append(operation)
    return _dump(update_memory(workspace_scope, operations=resolved_operations))


def remember_conversation_turn(
    workspace_scope: str | None,
    user_message: str,
    assistant_message: str,
    turn_id: str | None = None,
) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    return _dump(
        remember_turn(
            workspace_scope,
            user_message=user_message,
            assistant_message=assistant_message,
            turn_id=turn_id or _CURRENT_MEMORY_TURN_ID.get(),
        )
    )


def clear_conversation_memory(workspace_scope: str | None) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    return _dump(clear_cached_memory(workspace_scope))
