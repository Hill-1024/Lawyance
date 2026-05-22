"""
模块描述：聊天请求流水线，串联记忆同步、动态 prompt、历史压缩、Agent 运行和记忆写回。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional
import copy
import inspect
import json
import re
import time
import uuid

from mcp.memory_client import reset_current_memory_turn_id, set_current_memory_turn_id
from memory_system import MemoryRevisionConflict
from prompt_loader import build_system_memory

from schemas import ChatRequest
from services.agent_builder import build_agent
from services.conversation_state import active_conversations
from services.context_usage import (
    reset_current_context_usage_accumulator,
    set_current_context_usage_accumulator,
)
from services.history import compress_history
from services.memory_coordinator import (
    is_empty_reset_memory_snapshot,
    remember_memory_turn,
    retrieve_memory_context,
    sync_memory_cache,
)
from services.prompt_focus import current_focus
from services.workspace_service import get_workspace_scope


@dataclass
class PreparedChatTurn:
    content: str
    session_id: str
    stream: bool
    agent_mode: str
    workspace_scope: str
    turn_id: str
    agent: object


def sanitize_history(history: list[dict]) -> list[dict]:
    sanitized_history = []
    for msg in history:
        m = copy.deepcopy(msg)
        if m.get("role") == "system":
            continue
        if "content" not in m or m["content"] is None:
            m["content"] = ""
        else:
            m["content"] = str(m["content"])

        if "tool_calls" in m and m["tool_calls"]:
            for tc in m["tool_calls"]:
                if "function" in tc and "arguments" in tc["function"]:
                    if not isinstance(tc["function"]["arguments"], str):
                        tc["function"]["arguments"] = json.dumps(tc["function"]["arguments"])

        if "reasoning_content" in m and not m["reasoning_content"]:
            del m["reasoning_content"]

        if m.get("role") == "tool" and "tool_call_id" not in m:
            continue
        sanitized_history.append(m)
    return sanitized_history


def select_memory_sync_mode(request: ChatRequest) -> str:
    if request.memory_sync_mode in {"merge", "rebuild"}:
        return request.memory_sync_mode
    return "rebuild" if is_empty_reset_memory_snapshot(request.memory_snapshot) else "merge"


def load_memory_context(
    workspace_scope: str,
    content: str,
    sanitized_history: list[dict],
    request: ChatRequest,
) -> tuple[str, list[str]]:
    memory_sync_mode = select_memory_sync_mode(request)
    sync_memory_cache(
        workspace_scope,
        request.memory_snapshot,
        messages=sanitized_history if memory_sync_mode == "rebuild" else None,
        mode=memory_sync_mode,
        expected_revision=request.expected_revision,
        memory_conflict_strategy=request.memory_conflict_strategy,
    )
    memory_context, _payload = retrieve_memory_context(workspace_scope, content)
    return memory_context, current_focus(content, sanitized_history)


async def prepare_history(
    content: str,
    agent_mode: str,
    sanitized_history: list[dict],
    prompt_focus: list[str],
    memory_context: str,
    last_context_tokens: Optional[int] = None,
) -> list[dict]:
    full_history = build_system_memory(
        agent_mode=agent_mode,
        focus=prompt_focus,
        memory_context=memory_context,
    )
    full_history.extend(sanitized_history)
    processed_history = await compress_history(
        full_history,
        agent_mode=agent_mode,
        focus=prompt_focus,
        memory_context=memory_context,
        current_user_content=content,
        last_context_tokens=last_context_tokens,
    )
    processed_history.append({"role": "user", "content": content})
    return processed_history


async def prepare_chat_turn(request: ChatRequest, current_user: str) -> PreparedChatTurn:
    content = request.message
    session_id = request.conversation_id
    workspace_scope = get_workspace_scope(current_user, session_id)
    turn_id = f"turn_{uuid.uuid4().hex}"
    active_conversations[workspace_scope] = time.time()

    sanitized_history = sanitize_history(request.history)
    print(f"\n[收到请求] 会话ID: {session_id}, 模式: {request.agent_mode}, 流式: {request.stream}")

    memory_context, prompt_focus = load_memory_context(workspace_scope, content, sanitized_history, request)
    processed_history = await prepare_history(
        content,
        request.agent_mode,
        sanitized_history,
        prompt_focus,
        memory_context,
        request.last_context_tokens,
    )
    agent = build_agent(request.agent_mode, processed_history, session_id, workspace_scope, use_ocp=request.use_ocp)
    return PreparedChatTurn(
        content=content,
        session_id=session_id,
        stream=request.stream,
        agent_mode=request.agent_mode,
        workspace_scope=workspace_scope,
        turn_id=turn_id,
        agent=agent,
    )


def persist_turn(workspace_scope: str, content: str, assistant_content: str, turn_id: str) -> dict:
    return remember_memory_turn(workspace_scope, content, assistant_content, turn_id)


async def _run_agent(prepared: PreparedChatTurn, stream: bool):
    sig = inspect.signature(prepared.agent.run)
    if "stream" in sig.parameters:
        return prepared.agent.run(prepared.content, stream=stream)
    return prepared.agent.run(prepared.content)


async def run_agent_stream(prepared: PreparedChatTurn) -> AsyncIterator[dict]:
    full_result = ""
    memory_written = False
    turn_token = set_current_memory_turn_id(prepared.turn_id)
    usage_token, usage_accumulator = set_current_context_usage_accumulator()
    try:
        try:
            run_iter = await _run_agent(prepared, stream=True)
            async for chunk in run_iter:
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type")
                    if chunk_type == "content":
                        full_result += str(chunk.get("content") or "")
                    elif chunk_type == "content_replace":
                        full_result = str(chunk.get("content") or "")
                    elif chunk_type == "memory_candidate":
                        if not memory_written:
                            yield {"type": "thought", "thought_type": "memory", "mode": "new", "content": "正在整理记忆"}
                            memory_payload = persist_turn(
                                prepared.workspace_scope,
                                prepared.content,
                                str(chunk.get("content") or full_result),
                                prepared.turn_id,
                            )
                            memory_written = True
                            if memory_payload.get("memory"):
                                yield {"type": "memory_sync", "content": memory_payload["memory"]}
                            yield {"type": "thought", "thought_type": "memory", "mode": "new", "content": "记忆整理完成"}
                        continue
                    yield chunk
                elif chunk:
                    chunk_str = str(chunk)
                    if "[THOUGHT_SIGNATURE:" in chunk_str:
                        ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", chunk_str)
                        if ts_match:
                            ts = ts_match.group(1)
                            yield {"type": "thought_signature", "content": ts}
                            chunk_str = chunk_str.replace(ts_match.group(0), "")

                    if chunk_str:
                        full_result += chunk_str
                        yield {"type": "content", "content": chunk_str}
        finally:
            reset_current_context_usage_accumulator(usage_token)

        if not memory_written:
            yield {"type": "thought", "thought_type": "memory", "mode": "new", "content": "正在整理记忆"}
            memory_payload = persist_turn(prepared.workspace_scope, prepared.content, full_result, prepared.turn_id)
            if memory_payload.get("memory"):
                yield {"type": "memory_sync", "content": memory_payload["memory"]}
            yield {"type": "thought", "thought_type": "memory", "mode": "new", "content": "记忆整理完成"}
        usage_payload = usage_accumulator.payload()
        if usage_payload:
            yield {"type": "context_usage", "content": usage_payload}
    except Exception as e:
        print(f"[聊天流生成失败]: {type(e).__name__}: {e}")
        yield {"type": "error", "content": str(e)}
    finally:
        reset_current_memory_turn_id(turn_token)


async def run_agent_once(prepared: PreparedChatTurn) -> dict:
    turn_token = set_current_memory_turn_id(prepared.turn_id)
    usage_token, usage_accumulator = set_current_context_usage_accumulator()
    try:
        full_result = ""
        context_messages = []
        thought_signature = None
        memory_payload = {}
        memory_written = False

        try:
            run_iter = await _run_agent(prepared, stream=False)
            async for chunk in run_iter:
                if isinstance(chunk, dict):
                    if chunk.get("type") == "content":
                        full_result += chunk.get("content", "")
                    elif chunk.get("type") == "content_replace":
                        full_result = chunk.get("content", "")
                    elif chunk.get("type") == "thought_signature":
                        thought_signature = chunk.get("content")
                    elif chunk.get("type") == "history_trace":
                        messages = chunk.get("content") or []
                        if isinstance(messages, dict):
                            messages = [messages]
                        if isinstance(messages, list):
                            context_messages.extend(messages)
                    elif chunk.get("type") == "memory_candidate" and not memory_written:
                        memory_payload = persist_turn(
                            prepared.workspace_scope,
                            prepared.content,
                            str(chunk.get("content") or full_result),
                            prepared.turn_id,
                        )
                        memory_written = True
                elif chunk:
                    chunk_str = str(chunk)
                    if "[THOUGHT_SIGNATURE:" in chunk_str:
                        ts_match = re.search(r"\[THOUGHT_SIGNATURE:(.*?)]", chunk_str)
                        if ts_match:
                            thought_signature = ts_match.group(1)
                            chunk_str = chunk_str.replace(ts_match.group(0), "")
                    full_result += chunk_str
        finally:
            reset_current_context_usage_accumulator(usage_token)

        if not memory_written:
            memory_payload = persist_turn(prepared.workspace_scope, prepared.content, full_result, prepared.turn_id)
        result = {
            "reply": full_result,
            "download_path": None,
            "thought_signature": thought_signature,
            "context_messages": context_messages,
            "memory_snapshot": memory_payload.get("memory"),
        }
        usage_payload = usage_accumulator.payload()
        if usage_payload:
            result["context_usage"] = usage_payload
        return result
    finally:
        reset_current_memory_turn_id(turn_token)


__all__ = [
    "MemoryRevisionConflict",
    "load_memory_context",
    "persist_turn",
    "prepare_chat_turn",
    "prepare_history",
    "run_agent_once",
    "run_agent_stream",
    "sanitize_history",
    "select_memory_sync_mode",
    "sync_memory_cache",
]
