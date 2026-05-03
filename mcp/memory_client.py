import json
from typing import Any

from memory_system import (
    clear_conversation_memory as clear_cached_memory,
    remember_conversation_turn as remember_turn,
    retrieve_conversation_memory as retrieve_memory,
    sync_conversation_memory as sync_memory,
)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def sync_conversation_memory(workspace_scope: str | None, snapshot: Any = None, messages: list[dict] | None = None) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    return _dump(sync_memory(workspace_scope, snapshot=snapshot, messages=messages))


def retrieve_conversation_memory(workspace_scope: str | None, query: str, limit: int = 8) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope", "context": "", "items": []})
    return _dump(retrieve_memory(workspace_scope, query=query, limit=limit))


def remember_conversation_turn(workspace_scope: str | None, user_message: str, assistant_message: str) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    return _dump(remember_turn(workspace_scope, user_message=user_message, assistant_message=assistant_message))


def clear_conversation_memory(workspace_scope: str | None) -> str:
    if not workspace_scope:
        return _dump({"status": "error", "error": "missing workspace scope"})
    return _dump(clear_cached_memory(workspace_scope))
