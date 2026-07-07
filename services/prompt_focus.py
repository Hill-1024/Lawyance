"""
模块描述：当前轮动态 prompt 焦点与任务意图路由。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


GENERAL_FOCUS = "general_gate"
FILE_FOCUS = "file_processing"
LEGAL_FOCUS = "legal_retrieval"
DEFAULT_PROMPT_FOCUS = (GENERAL_FOCUS,)
SAFE_PROMPT_FOCUS = (GENERAL_FOCUS, FILE_FOCUS, LEGAL_FOCUS)

ROUTER_MODE_ENV = "CONTEXT_ROUTER_MODE"
ROUTER_THRESHOLD_ENV = "CONTEXT_ROUTER_CONFIDENCE_THRESHOLD"
DEFAULT_ROUTER_MODE = "hybrid"
DEFAULT_ROUTER_CONFIDENCE_THRESHOLD = 0.7

LEGAL_PATTERNS = (
    r"法条|法律|法规|司法解释|案例|判例|裁判|民法典|劳动法|公司法|行政诉讼|刑事|民事|仲裁",
    r"起诉|应诉|答辩|诉讼|管辖|举证|质证|赔偿|违约|侵权|工伤|解除合同|律师函|法律意见",
)
FILE_PATTERNS = (
    r"上传|附件|文件|文档|材料|卷宗|合同|协议|简历|证据|读取|分析|审查|批注|生成文书",
    r"\.(?:pdf|docx?|txt|md|xlsx?|pptx?)(?:\b|$)",
)
ARCHITECTURE_PATTERNS = (
    r"架构|代码|后端|前端|接口|模块|重构|迁移|上下文|记忆系统|agent|prompt|测试|实现",
)
MEMORY_PATTERNS = (
    r"记住|记忆|之前|前面|刚才|上次|后续|偏好|约束|上下文",
)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if 0 < value <= 1 else default


def _router_mode() -> str:
    mode = (os.getenv(ROUTER_MODE_ENV) or DEFAULT_ROUTER_MODE).strip().lower()
    return mode if mode in {"hybrid", "rules", "llm"} else DEFAULT_ROUTER_MODE


def _score_patterns(text: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE))


def _ordered_focus(*items: str) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result or [GENERAL_FOCUS]


def route_intent_rules(content: str, history: list[dict] | None = None) -> dict[str, Any]:
    text = str(content or "")
    recent_history = "\n".join(str((msg or {}).get("content") or "") for msg in (history or [])[-4:])
    combined = f"{recent_history}\n{text}"
    legal_score = _score_patterns(combined, LEGAL_PATTERNS)
    file_score = _score_patterns(combined, FILE_PATTERNS)
    architecture_score = _score_patterns(combined, ARCHITECTURE_PATTERNS)
    memory_score = _score_patterns(combined, MEMORY_PATTERNS)

    reasons: list[str] = []
    focus = [GENERAL_FOCUS]
    task_type = "general"
    confidence = 0.55

    if legal_score:
        reasons.append("legal_keyword")
        focus.append(LEGAL_FOCUS)
        task_type = "legal_retrieval"
        confidence = max(confidence, 0.74 + min(legal_score, 2) * 0.08)
    if file_score:
        reasons.append("file_keyword")
        focus.append(FILE_FOCUS)
        task_type = "file_processing" if not legal_score else "legal_file_review"
        confidence = max(confidence, 0.76 + min(file_score, 2) * 0.07)
    if architecture_score and not legal_score and not file_score:
        reasons.append("architecture_keyword")
        task_type = "architecture"
        confidence = max(confidence, 0.76)
    if memory_score and not legal_score and not file_score:
        reasons.append("memory_keyword")
        task_type = "memory_context"
        confidence = max(confidence, 0.68)

    return {
        "task_type": task_type,
        "confidence": min(confidence, 0.96),
        "focus": _ordered_focus(*focus),
        "reasons": reasons or ["default_general"],
        "source": "rules",
        "requires_legal_evidence": bool(legal_score),
        "requires_file_read": bool(file_score),
        "requires_workspace_listing": bool(file_score),
        "requires_memory_deep_search": bool(memory_score),
    }


def _coerce_llm_intent(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None

    allowed_focus = {GENERAL_FOCUS, FILE_FOCUS, LEGAL_FOCUS}
    focus = payload.get("focus")
    if not isinstance(focus, list):
        focus = []
    focus = [str(item) for item in focus if str(item) in allowed_focus]
    if not focus:
        focus = [GENERAL_FOCUS]
    if GENERAL_FOCUS not in focus:
        focus.insert(0, GENERAL_FOCUS)

    try:
        confidence = float(payload.get("confidence", 0.65))
    except (TypeError, ValueError):
        confidence = 0.65
    reasons = payload.get("reasons")
    if not isinstance(reasons, list):
        reasons = ["llm_classifier"]

    return {
        "task_type": str(payload.get("task_type") or "general"),
        "confidence": max(0.0, min(confidence, 1.0)),
        "focus": _ordered_focus(*focus),
        "reasons": [str(item)[:80] for item in reasons[:6]],
        "source": "llm",
        "requires_legal_evidence": bool(payload.get("requires_legal_evidence")),
        "requires_file_read": bool(payload.get("requires_file_read")),
        "requires_workspace_listing": bool(payload.get("requires_workspace_listing")),
        "requires_memory_deep_search": bool(payload.get("requires_memory_deep_search")),
    }


async def classify_intent_with_llm(content: str, history: list[dict] | None = None) -> dict[str, Any] | None:
    from function_calling import call
    from prompt_loader import build_system_memory

    recent = [
        {"role": msg.get("role"), "content": str(msg.get("content") or "")[:1200]}
        for msg in (history or [])[-6:]
        if isinstance(msg, dict)
    ]
    prompt = json.dumps(
        {
            "current_user_message": str(content or "")[:2400],
            "recent_history": recent,
        },
        ensure_ascii=False,
    )
    response = await call(
        build_system_memory(task="intent_router") + [{"role": "user", "content": prompt}],
        stream=False,
        include_tools=False,
    )
    return _coerce_llm_intent(getattr(response, "content", "") or "")


async def resolve_intent(content: str, history: list[dict] | None = None) -> dict[str, Any]:
    rules = route_intent_rules(content, history)
    mode = _router_mode()
    threshold = _float_env(ROUTER_THRESHOLD_ENV, DEFAULT_ROUTER_CONFIDENCE_THRESHOLD)
    if mode == "rules":
        return rules
    if mode == "hybrid" and rules["confidence"] >= threshold:
        return rules

    try:
        llm_intent = await classify_intent_with_llm(content, history)
    except Exception as exc:
        fallback = dict(rules)
        fallback["source"] = "rules_fallback"
        fallback["reasons"] = list(fallback.get("reasons", [])) + [f"llm_failed:{type(exc).__name__}"]
        return fallback
    if not llm_intent:
        fallback = dict(rules)
        fallback["source"] = "rules_fallback"
        fallback["reasons"] = list(fallback.get("reasons", [])) + ["llm_empty"]
        return fallback

    merged = dict(llm_intent)
    merged["focus"] = _ordered_focus(*(list(rules.get("focus", [])) + list(llm_intent.get("focus", []))))
    for key in (
        "requires_legal_evidence",
        "requires_file_read",
        "requires_workspace_listing",
        "requires_memory_deep_search",
    ):
        merged[key] = bool(rules.get(key) or llm_intent.get(key))
    merged["reasons"] = list(rules.get("reasons", [])) + list(llm_intent.get("reasons", []))
    return merged


def current_focus(content: str, history: list[dict]) -> list[str]:
    return list(route_intent_rules(content, history).get("focus") or DEFAULT_PROMPT_FOCUS)
