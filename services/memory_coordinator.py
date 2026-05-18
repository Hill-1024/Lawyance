"""
模块描述：对话记忆工具协调层，封装通过 mcps 黑箱访问记忆系统的固定流程。
"""

from typing import Any, List, Optional
import json

from memory_system import MemoryRevisionConflict
from mcps import use_tools


MEMORY_SNAPSHOT_FIELD = "memory_snapshot"


def read_tool_json(tool_result: Any) -> dict:
    if isinstance(tool_result, dict):
        return tool_result
    if not isinstance(tool_result, str):
        return {}
    try:
        parsed = json.loads(tool_result)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def call_memory_tool(tool_name: str, arguments: dict, workspace_scope: str) -> dict:
    return read_tool_json(use_tools(tool_name, arguments, conv_id=workspace_scope))


def sync_memory_cache(
    workspace_scope: str,
    snapshot: Optional[dict],
    messages: Optional[List[dict]] = None,
    mode: str = "merge",
    expected_revision: Optional[int] = None,
    memory_conflict_strategy: Optional[str] = None,
) -> dict:
    return call_memory_tool(
        "sync_conversation_memory",
        {
            "snapshot": snapshot or {},
            "messages": messages,
            "mode": mode,
            "expected_revision": expected_revision,
            "memory_conflict_strategy": memory_conflict_strategy,
        },
        workspace_scope,
    )


def retrieve_memory_context(workspace_scope: str, query: str) -> tuple[str, dict]:
    payload = call_memory_tool(
        "retrieve_conversation_memory",
        {
            "query": query,
            "limit": 8,
        },
        workspace_scope,
    )
    return str(payload.get("context") or ""), payload


def memory_conflict_detail(exc: MemoryRevisionConflict) -> dict:
    return {
        "error": "memory_revision_conflict",
        "expected_revision": exc.expected_revision,
        "actual_revision": exc.actual_revision,
        MEMORY_SNAPSHOT_FIELD: exc.snapshot,
    }


def is_empty_reset_memory_snapshot(snapshot: Optional[dict]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    try:
        revision = int(snapshot.get("revision", 0) or 0)
    except (TypeError, ValueError):
        revision = 0
    return (
        revision == 0
        and not snapshot.get("events")
        and not snapshot.get("facts")
        and not snapshot.get("focus")
    )


def remember_memory_turn(workspace_scope: str, user_message: str, assistant_message: str, turn_id: str | None = None) -> dict:
    return call_memory_tool(
        "remember_conversation_turn",
        {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "turn_id": turn_id,
        },
        workspace_scope,
    )
