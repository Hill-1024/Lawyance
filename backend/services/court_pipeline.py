"""
模块描述：模拟法庭单回合流水线，组装角色上下文、工具 scope、流式输出和记忆写回。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator
import asyncio
import json
import logging
import time
import uuid

from agents import ToolLoopAgent
from mcps import (
    MemoryRevisionConflict,
    court_tools,
    reset_current_memory_turn_id,
    set_current_memory_turn_id,
    use_tools,
)
from schemas import CourtTurnRequest
from context_usage import (
    reset_current_context_usage_accumulator,
    set_current_context_usage_accumulator,
)
from services.conversation_state import active_conversations
from services.court_fsm import CourtDecision, decide_next_turn, normalise_case_type
from services.court_prompts import build_court_messages
from services.court_transcript import prepare_public_transcript, render_public_context, speaker_label
from services.memory_coordinator import (
    memory_conflict_detail,
    remember_memory_turn,
    retrieve_memory_context,
    sync_memory_cache,
)
from services.workspace_service import get_workspace_scope


logger = logging.getLogger(__name__)


MEMORY_TOOL_NAMES = {
    "retrieve_conversation_memory",
    "inspect_conversation_memory",
    "update_conversation_memory",
}


@dataclass
class PreparedCourtTurn:
    request: CourtTurnRequest
    base_scope: str
    role_scope: str | None
    turn_id: str
    decision: CourtDecision
    public_summary: str
    recent_events: list[dict[str, Any]]
    agent: ToolLoopAgent | None
    is_user_agent: bool = False


def role_memory_scope(base_scope: str, speaker: str) -> str:
    return f"{base_scope}:{speaker}"


def role_scopes(base_scope: str) -> dict[str, str]:
    return {
        "judge": role_memory_scope(base_scope, "judge"),
        "opponent": role_memory_scope(base_scope, "opponent"),
        "reviewer": role_memory_scope(base_scope, "reviewer"),
        "user": role_memory_scope(base_scope, "user"),
    }


def build_court_tool_executor(base_scope: str, role_scope: str):
    # arguments 由 ToolLoopAgent._parse_arguments / mcps 转发面处理，
    # 这里只负责按工具名挑选记忆 scope 后转发。
    def execute_tool(tool_name: str, arguments):
        scope = role_scope if tool_name in MEMORY_TOOL_NAMES else base_scope
        return use_tools(tool_name, arguments, scope, capability="court")

    return execute_tool


def _agent_state(request: CourtTurnRequest, speaker: str) -> dict[str, Any]:
    states = request.agent_states if isinstance(request.agent_states, dict) else {}
    state = states.get(speaker)
    return state if isinstance(state, dict) else {}


def _sync_and_retrieve_role_memory(request: CourtTurnRequest, role_scope: str, speaker: str, query: str) -> str:
    snapshot = _agent_state(request, speaker).get("memory_snapshot")
    sync_memory_cache(role_scope, snapshot, messages=None, mode="merge")
    memory_context, _payload = retrieve_memory_context(role_scope, query)
    return memory_context


def _cross_role_memory_context(base_scope: str, request: CourtTurnRequest) -> str:
    """复盘员可读法官、对方律师、以及用户方代理的私有记忆摘要。"""
    lines = []
    for speaker in ("judge", "opponent", "user"):
        scope = role_memory_scope(base_scope, speaker)
        snapshot = _agent_state(request, speaker).get("memory_snapshot")
        try:
            sync_memory_cache(scope, snapshot, messages=None, mode="merge")
            memory_context, _payload = retrieve_memory_context(scope, "庭审争点、风险、已暴露漏洞")
        except Exception:
            logger.exception("Failed to load cross-role memory for %s", speaker)
            memory_context = "读取失败"
        if memory_context.strip():
            label = "用户方代理" if speaker == "user" else speaker_label(speaker)
            lines.append(f"【{label}】\n{memory_context.strip()}")
    return "\n\n".join(lines)


async def prepare_court_turn(request: CourtTurnRequest, current_user: str) -> PreparedCourtTurn:
    base_scope = get_workspace_scope(current_user, request.court_session_id)
    active_conversations[base_scope] = time.time()

    public_summary, recent_events = prepare_public_transcript(
        request.public_summary,
        request.public_events_recent,
    )
    decision = decide_next_turn(request.court_state, recent_events)
    turn_id = f"court_turn_{uuid.uuid4().hex}"

    raw_state = request.court_state if isinstance(request.court_state, dict) else {}
    user_agent_enabled = bool(raw_state.get("user_agent_enabled"))
    is_user_agent = False

    # 用户开启"我方代理"后，把 FSM 决出的"等用户"重写为 user_agent 接管发言。
    # 此处同步推进 phase 计数（与前端 appendUserEvent 路径互斥），保证 alternating 阶段正确推进。
    if decision.awaiting_user and user_agent_enabled and not decision.trial_over:
        next_state = dict(decision.court_state)
        next_state["awaiting_user"] = False
        phase = str(next_state.get("phase") or "")
        counts = dict(next_state.get("phase_turn_counts") or {})
        if phase:
            counts[phase] = int(counts.get(phase, 0) or 0) + 1
        next_state["phase_turn_counts"] = counts
        total = int(next_state.get("total_turns") or 0) + 1
        next_state["total_turns"] = total
        positions = dict(next_state.get("speaker_last_positions") or {})
        positions["user"] = total
        next_state["speaker_last_positions"] = positions
        decision = CourtDecision(
            speaker="user",
            phase=decision.phase,
            court_state=next_state,
            trial_over=False,
            awaiting_user=False,
        )
        is_user_agent = True

    if not decision.speaker:
        return PreparedCourtTurn(
            request=request,
            base_scope=base_scope,
            role_scope=None,
            turn_id=turn_id,
            decision=decision,
            public_summary=public_summary,
            recent_events=recent_events,
            agent=None,
            is_user_agent=False,
        )

    speaker = decision.speaker
    role_scope = role_memory_scope(base_scope, speaker)
    query = render_public_context(public_summary, recent_events)
    memory_context = await asyncio.to_thread(
        _sync_and_retrieve_role_memory,
        request,
        role_scope,
        speaker,
        query,
    )
    cross_role_memory = await asyncio.to_thread(_cross_role_memory_context, base_scope, request) if speaker == "reviewer" else ""
    messages = build_court_messages(
        speaker=speaker,
        case_type=normalise_case_type(decision.court_state.get("case_type")),
        user_side=str(decision.court_state.get("user_side") or ""),
        court_state=decision.court_state,
        shared_dossier=request.shared_dossier,
        private_brief=request.private_brief,
        public_summary=public_summary,
        recent_events=recent_events,
        memory_context=memory_context,
        cross_role_memory=cross_role_memory,
    )
    agent = ToolLoopAgent(
        memory=messages,
        session_id=request.court_session_id,
        workspace_scope=base_scope,
        use_ocp=False,
        execute_tool=build_court_tool_executor(base_scope, role_scope),
        mode=f"court_{speaker}",
        tools=court_tools,
        final_answer_source="plain_text",
    )
    return PreparedCourtTurn(
        request=request,
        base_scope=base_scope,
        role_scope=role_scope,
        turn_id=turn_id,
        decision=decision,
        public_summary=public_summary,
        recent_events=recent_events,
        agent=agent,
        is_user_agent=is_user_agent,
    )


def _with_court_meta(prepared: PreparedCourtTurn, event: dict[str, Any]) -> dict[str, Any]:
    """给非 court_state 事件附 speaker/phase 元信息。court_state 只在显式事件中下发。"""
    speaker = prepared.decision.speaker
    enriched = dict(event)
    if speaker:
        enriched.setdefault("speaker", speaker)
    enriched.setdefault("phase", prepared.decision.phase)
    if prepared.is_user_agent:
        enriched.setdefault("by_user_agent", True)
    return enriched


def _memory_user_payload(prepared: PreparedCourtTurn) -> str:
    return (
        "庭审公开进展：\n"
        + render_public_context(prepared.public_summary, prepared.recent_events)
        + "\n\n结构化庭审状态：\n"
        + json.dumps(prepared.decision.court_state, ensure_ascii=False, sort_keys=True)
    )


async def run_court_turn_stream(prepared: PreparedCourtTurn) -> AsyncIterator[dict[str, Any]]:
    yield {
        "type": "court_state",
        "content": prepared.decision.court_state,
        "speaker": prepared.decision.speaker,
        "phase": prepared.decision.phase,
        "court_state": prepared.decision.court_state,
        "transcript_summary": prepared.public_summary,
        "by_user_agent": prepared.is_user_agent,
    }
    if not prepared.agent or not prepared.decision.speaker:
        return

    full_result = ""
    turn_token = set_current_memory_turn_id(prepared.turn_id)
    usage_token, usage_accumulator = set_current_context_usage_accumulator()
    try:
        async for chunk in prepared.agent.run(stream=True):
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                if chunk_type == "content":
                    full_result += str(chunk.get("content") or "")
                elif chunk_type == "content_replace":
                    full_result = str(chunk.get("content") or "")
                yield _with_court_meta(prepared, chunk)
            elif chunk:
                chunk_str = str(chunk)
                full_result += chunk_str
                yield _with_court_meta(prepared, {"type": "content", "content": chunk_str})
    finally:
        reset_current_context_usage_accumulator(usage_token)
        reset_current_memory_turn_id(turn_token)

    if prepared.role_scope:
        memory_payload = await asyncio.to_thread(
            remember_memory_turn,
            prepared.role_scope,
            _memory_user_payload(prepared),
            full_result,
            prepared.turn_id,
        )
        if memory_payload.get("memory"):
            yield _with_court_meta(
                prepared,
                {
                    "type": "memory_sync",
                    "content": memory_payload["memory"],
                    "turn_id": prepared.turn_id,
                },
            )

    usage_payload = usage_accumulator.payload()
    if usage_payload:
        yield _with_court_meta(prepared, {"type": "context_usage", "content": usage_payload})


__all__ = [
    "MEMORY_TOOL_NAMES",
    "MemoryRevisionConflict",
    "build_court_tool_executor",
    "memory_conflict_detail",
    "prepare_court_turn",
    "role_memory_scope",
    "role_scopes",
    "run_court_turn_stream",
]
