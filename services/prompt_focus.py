"""
模块描述：当前轮动态 prompt 焦点与任务意图路由。
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any


GENERAL_FOCUS = "general_gate"
FILE_FOCUS = "file_processing"
LEGAL_FOCUS = "legal_retrieval"
DEFAULT_PROMPT_FOCUS = (GENERAL_FOCUS,)
SAFE_PROMPT_FOCUS = (GENERAL_FOCUS, FILE_FOCUS, LEGAL_FOCUS)
SAFE_TASK_TYPES = {
    "general",
    "legal_retrieval",
    "file_processing",
    "legal_file_review",
    "architecture",
    "memory_context",
}

ROUTER_MODE_ENV = "CONTEXT_ROUTER_MODE"
ROUTER_THRESHOLD_ENV = "CONTEXT_ROUTER_CONFIDENCE_THRESHOLD"
DEFAULT_ROUTER_MODE = "hybrid"
DEFAULT_ROUTER_CONFIDENCE_THRESHOLD = 0.7

LEGAL_PATTERNS = (
    r"法条|法律|法规|司法解释|案例|判例|裁判|民法典|劳动法|公司法|行政诉讼|刑事|民事|仲裁",
    r"起诉|应诉|答辩|诉讼|管辖|举证|质证|赔偿|违约|侵权|工伤|解除合同|律师函|法律意见",
)
# 焦点/任务类型判定：允许宽松，命中只影响注入哪段 prompt。
FILE_PATTERNS = (
    r"上传|附件|文件|文档|材料|卷宗|合同|协议|简历|证据|读取|分析|审查|批注|生成文书",
    r"\.(?:pdf|docx?|txt|md|xlsx?|pptx?)(?:\b|$)",
)
# 附件关键词仅作为工具建议，不能证明工作区确实存在可读文件。
# 避免把“要准备哪些材料”等纯文本问题直接解释为读文件任务。
FILE_ATTACHMENT_PATTERNS = (
    r"上传|附件|工作区|卷宗|批注|扫描件|压缩包",
    r"\.(?:pdf|docx?|xlsx?|pptx?|txt|md)(?:\b|$)",
    r"(?:这份|这个|上述|以下|附件中|上传的|我传的|我发的).{0,8}"
    r"(?:文件|文档|合同|协议|表格|材料|简历|报告|清单|标书|判决书|裁定书|图片|截图|照片|图)",
    r"(?:图片|截图|照片|图像)",
    r"(?:读取|看一下|看看|读一下|分析|审查|审阅|批注).{0,4}(?:文件|文档|合同|附件|图片)",
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


def _history_text(history: list[dict] | None, *, roles: set[str] | None = None) -> str:
    """按角色过滤历史文本；默认剔除助手自己的输出。"""
    allowed = roles or {"user"}
    lines = []
    for msg in (history or [])[-4:]:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "") not in allowed:
            continue
        lines.append(str(msg.get("content") or ""))
    return "\n".join(lines)


def route_intent_rules(content: str, history: list[dict] | None = None) -> dict[str, Any]:
    text = str(content or "")
    # 规则层的工具建议只看本轮；历史用户主题仅补充焦点。
    # 不使用助手欢迎语，也不让历史关键词抬高本轮置信度而跳过语义路由。
    history_topic = _history_text(history, roles={"user"})
    topic_text = f"{history_topic}\n{text}"
    legal_score = _score_patterns(text, LEGAL_PATTERNS)
    legal_topic_score = _score_patterns(topic_text, LEGAL_PATTERNS)
    current_file_score = _score_patterns(text, FILE_PATTERNS)
    attachment_score = _score_patterns(text, FILE_ATTACHMENT_PATTERNS)
    file_score = _score_patterns(topic_text, FILE_PATTERNS)
    architecture_score = _score_patterns(text, ARCHITECTURE_PATTERNS)
    memory_score = _score_patterns(text, MEMORY_PATTERNS)

    reasons: list[str] = []
    focus = [GENERAL_FOCUS]
    task_type = "general"
    confidence = 0.55

    if legal_topic_score:
        reasons.append("legal_keyword")
        focus.append(LEGAL_FOCUS)
        task_type = "legal_retrieval"
        if legal_score:
            confidence = max(confidence, 0.74 + min(legal_score, 2) * 0.08)
    if file_score:
        reasons.append("file_keyword")
        focus.append(FILE_FOCUS)
        task_type = "file_processing" if not legal_topic_score else "legal_file_review"
        if current_file_score:
            confidence = max(confidence, 0.76 + min(current_file_score, 2) * 0.07)
    if attachment_score:
        reasons.append("attachment_keyword")
        focus.append(FILE_FOCUS)
        task_type = "file_processing" if not legal_topic_score else "legal_file_review"
        confidence = max(confidence, 0.76)
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
        "requires_file_read": bool(attachment_score),
        "requires_workspace_listing": bool(attachment_score),
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
    if not math.isfinite(confidence):
        confidence = 0.65
    reasons = payload.get("reasons")
    if not isinstance(reasons, list):
        reasons = ["llm_classifier"]

    task_type = str(payload.get("task_type") or "general")
    if task_type not in SAFE_TASK_TYPES:
        task_type = "general"

    def strict_bool(key: str) -> bool:
        return payload.get(key) is True

    return {
        "task_type": task_type,
        "confidence": max(0.0, min(confidence, 1.0)),
        "focus": _ordered_focus(*focus),
        "reasons": [str(item)[:80] for item in reasons[:6]],
        "source": "llm",
        "requires_legal_evidence": strict_bool("requires_legal_evidence"),
        "requires_file_read": strict_bool("requires_file_read"),
        "requires_workspace_listing": strict_bool("requires_workspace_listing"),
        "requires_memory_deep_search": strict_bool("requires_memory_deep_search"),
    }


async def classify_intent_with_llm(content: str, history: list[dict] | None = None) -> dict[str, Any] | None:
    from function_calling import call
    from prompt_loader import build_system_memory

    recent = [
        {"role": msg.get("role"), "content": str(msg.get("content") or "")[:1200]}
        for msg in (history or [])[-6:]
        if isinstance(msg, dict) and str(msg.get("role") or "") == "user"
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
    # 路由只提供回答前的工具建议，不再驱动最终回答后的修复循环。
    # 保留语义路由对指代附件、历史追问和记忆检索的补充能力。
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
