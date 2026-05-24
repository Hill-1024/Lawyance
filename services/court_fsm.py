"""
模块描述：模拟法庭阶段状态机，负责从结构化庭审状态与用户立场推导下一位发言者。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


COURT_SPEAKERS = {"judge", "opponent", "reviewer"}

PHASES_BY_CASE_TYPE: dict[str, list[str]] = {
    "civil": [
        "opening",
        "claim_statement",
        "defense_response",
        "court_inquiry",
        "evidence_cross",
        "court_debate",
        "final_statement",
        "judge_summary",
        "review",
    ],
    "administrative": [
        "opening",
        "claim_statement",
        "agency_response",
        "court_inquiry",
        "legality_review",
        "court_debate",
        "judge_summary",
        "review",
    ],
    "criminal": [
        "opening",
        "prosecution_statement",
        "defense_response",
        "court_inquiry",
        "evidence_cross",
        "court_debate",
        "final_statement",
        "judge_summary",
        "review",
    ],
}

# 每个阶段由哪一方主导发言。
#   judge / reviewer  —— 法庭主导，单一发言人。
#   plaintiff         —— 原告 / 行政相对人 / 公诉方（"诉方"）。
#   defendant         —— 被告 / 行政机关 / 辩护方（"答辩方"）。
#   alternating       —— 双方轮流（举证质证、法庭辩论等）。
PHASE_OWNERS_BY_CASE: dict[str, dict[str, str]] = {
    "civil": {
        "opening": "judge",
        "claim_statement": "plaintiff",
        "defense_response": "defendant",
        "court_inquiry": "judge",
        "evidence_cross": "alternating",
        "court_debate": "alternating",
        "final_statement": "alternating",
        "judge_summary": "judge",
        "review": "reviewer",
    },
    "administrative": {
        "opening": "judge",
        "claim_statement": "plaintiff",
        "agency_response": "defendant",
        "court_inquiry": "judge",
        "legality_review": "judge",
        "court_debate": "alternating",
        "judge_summary": "judge",
        "review": "reviewer",
    },
    "criminal": {
        "opening": "judge",
        "prosecution_statement": "plaintiff",
        "defense_response": "defendant",
        "court_inquiry": "judge",
        "evidence_cross": "alternating",
        "court_debate": "alternating",
        "final_statement": "defendant",
        "judge_summary": "judge",
        "review": "reviewer",
    },
}

PHASE_TURN_LIMITS: dict[str, int] = {
    "opening": 1,
    "claim_statement": 1,
    "defense_response": 1,
    "agency_response": 1,
    "prosecution_statement": 1,
    "court_inquiry": 3,
    "legality_review": 2,
    "evidence_cross": 4,
    "court_debate": 4,
    "final_statement": 2,
    "judge_summary": 1,
    "review": 1,
}

# 法官说完之后需要等用户回应的阶段（用户与对方轮流回应法官询问）。
JUDGE_AWAIT_PHASES = {"court_inquiry", "legality_review"}

PLAINTIFF_SIDES = {"原告", "原告（行政相对人）", "公诉方"}
DEFENDANT_SIDES = {"被告", "行政机关（被告）", "辩护方"}


@dataclass(frozen=True)
class CourtDecision:
    speaker: str | None
    phase: str
    court_state: dict[str, Any]
    trial_over: bool = False
    awaiting_user: bool = False


def normalise_case_type(case_type: Any) -> str:
    value = str(case_type or "civil").strip()
    return value if value in PHASES_BY_CASE_TYPE else "civil"


def _user_role(user_side: Any) -> str:
    """把用户立场字符串映射到 plaintiff/defendant 角色。"""
    text = str(user_side or "").strip()
    if text in PLAINTIFF_SIDES:
        return "plaintiff"
    if text in DEFENDANT_SIDES:
        return "defendant"
    if any(keyword in text for keyword in ("原告", "公诉", "相对人")):
        return "plaintiff"
    if any(keyword in text for keyword in ("被告", "辩护", "机关")):
        return "defendant"
    return "plaintiff"


def _opposite_role(role: str) -> str:
    return "defendant" if role == "plaintiff" else "plaintiff"


def initial_court_state(case_type: str = "civil", user_side: str = "") -> dict[str, Any]:
    resolved_case_type = normalise_case_type(case_type)
    return {
        "case_type": resolved_case_type,
        "user_side": str(user_side or ""),
        "phase": PHASES_BY_CASE_TYPE[resolved_case_type][0],
        "phase_turn_counts": {},
        "total_turns": 0,
        "pending_interjection": False,
        "awaiting_user": False,
        "forced_advance_requested": False,
        "speaker_last_positions": {},
        "trial_over": False,
    }


def _phase_list(case_type: str) -> list[str]:
    return PHASES_BY_CASE_TYPE[normalise_case_type(case_type)]


def _coerce_state(raw_state: dict[str, Any] | None) -> dict[str, Any]:
    raw_state = raw_state if isinstance(raw_state, dict) else {}
    state = initial_court_state(raw_state.get("case_type", "civil"), raw_state.get("user_side", ""))
    state.update({key: deepcopy(value) for key, value in raw_state.items() if key in state})
    state["case_type"] = normalise_case_type(state.get("case_type"))
    phases = _phase_list(state["case_type"])
    if state.get("phase") not in phases:
        state["phase"] = phases[0]
    if not isinstance(state.get("phase_turn_counts"), dict):
        state["phase_turn_counts"] = {}
    if not isinstance(state.get("speaker_last_positions"), dict):
        state["speaker_last_positions"] = {}
    state["total_turns"] = int(state.get("total_turns") or 0)
    return state


def _advance_phase(state: dict[str, Any]) -> None:
    phases = _phase_list(state["case_type"])
    index = phases.index(state["phase"])
    if index >= len(phases) - 1:
        state["trial_over"] = True
        state["awaiting_user"] = False
        state["forced_advance_requested"] = False
        return
    state["phase"] = phases[index + 1]
    state["awaiting_user"] = False
    state["forced_advance_requested"] = False


def _last_public_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events or []):
        if isinstance(event, dict):
            return event
    return {}


def _last_speech_role(events: list[dict[str, Any]], user_side: str) -> str | None:
    """根据最近一条非系统发言推断说话方的诉/答角色。"""
    for event in reversed(events or []):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system":
            continue
        speaker = str(event.get("speaker") or "")
        if speaker == "user":
            return _user_role(user_side)
        if speaker == "opponent":
            return _opposite_role(_user_role(user_side))
        # judge / reviewer / system 不算 plaintiff/defendant 角色。
        return None
    return None


def _last_ai_yields(events: list[dict[str, Any]]) -> bool:
    last = _last_public_event(events)
    if last.get("speaker") not in COURT_SPEAKERS:
        return False
    content = str(last.get("content") or "")
    return any(marker in content for marker in ("无更多意见", "没有更多意见", "不再补充", "暂无补充"))


def _phase_limit_reached(state: dict[str, Any]) -> bool:
    phase = str(state.get("phase") or "")
    count = int((state.get("phase_turn_counts") or {}).get(phase, 0) or 0)
    return count >= PHASE_TURN_LIMITS.get(phase, 2)


def _select_role(state: dict[str, Any], public_events: list[dict[str, Any]]) -> str:
    """返回下一发言角色：judge / reviewer / plaintiff / defendant。"""
    if state.get("pending_interjection"):
        return "judge"
    case_type = state["case_type"]
    phase = state["phase"]
    owner = PHASE_OWNERS_BY_CASE.get(case_type, {}).get(phase, "alternating")
    if owner in {"judge", "reviewer", "plaintiff", "defendant"}:
        return owner
    # alternating：根据上一发言方翻转。
    last_role = _last_speech_role(public_events, str(state.get("user_side") or ""))
    if last_role == "plaintiff":
        return "defendant"
    if last_role == "defendant":
        return "plaintiff"
    # 没有可推断的上一方时，按"诉方先开口"惯例起头。
    return "plaintiff"


def _role_to_speaker(role: str, user_side: str) -> str:
    """把角色映射到实际发言者：user / opponent / judge / reviewer。"""
    if role in {"judge", "reviewer"}:
        return role
    return "user" if role == _user_role(user_side) else "opponent"


def decide_next_turn(raw_state: dict[str, Any] | None, public_events: list[dict[str, Any]] | None = None) -> CourtDecision:
    state = _coerce_state(raw_state)
    public_events = public_events or []

    if state.get("trial_over"):
        return CourtDecision(None, state["phase"], state, trial_over=True)

    if state.get("awaiting_user") and not state.get("forced_advance_requested"):
        return CourtDecision(None, state["phase"], state, awaiting_user=True)

    if state.get("forced_advance_requested") or _phase_limit_reached(state) or _last_ai_yields(public_events):
        _advance_phase(state)
        if state.get("trial_over"):
            return CourtDecision(None, state["phase"], state, trial_over=True)

    role = _select_role(state, public_events)
    user_side = str(state.get("user_side") or "")
    speaker = _role_to_speaker(role, user_side)

    next_state = deepcopy(state)
    next_state["pending_interjection"] = False
    next_state["forced_advance_requested"] = False

    if speaker == "user":
        # 等用户陈述；不计 turn，由前端在用户发言后递增 phase 计数。
        next_state["awaiting_user"] = True
        return CourtDecision(None, next_state["phase"], next_state, awaiting_user=True)

    next_state["awaiting_user"] = speaker == "judge" and next_state["phase"] in JUDGE_AWAIT_PHASES
    next_state["total_turns"] = int(next_state.get("total_turns") or 0) + 1
    counts = dict(next_state.get("phase_turn_counts") or {})
    counts[next_state["phase"]] = int(counts.get(next_state["phase"], 0) or 0) + 1
    next_state["phase_turn_counts"] = counts
    positions = dict(next_state.get("speaker_last_positions") or {})
    positions[speaker] = next_state["total_turns"]
    next_state["speaker_last_positions"] = positions
    if next_state["phase"] == "review" and speaker == "reviewer":
        next_state["trial_over"] = True
        next_state["awaiting_user"] = False

    return CourtDecision(speaker, next_state["phase"], next_state, trial_over=bool(next_state.get("trial_over")))


__all__ = [
    "COURT_SPEAKERS",
    "PHASES_BY_CASE_TYPE",
    "PHASE_OWNERS_BY_CASE",
    "PHASE_TURN_LIMITS",
    "JUDGE_AWAIT_PHASES",
    "CourtDecision",
    "decide_next_turn",
    "initial_court_state",
    "normalise_case_type",
]
