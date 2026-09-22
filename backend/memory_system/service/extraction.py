from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from typing import Any

from .state import *
from .utils import *
from .schema import _prefer_newer

def _event_from_message(role: str, content: Any, turn_id: str | None = None, sequence: int | None = None) -> dict[str, Any] | None:
    if role not in {"user", "assistant", "system"}:
        return None
    text = _strip_message_noise(content)
    if not text:
        return None
    if role == "assistant" and "您好，我是 **Lawver**" in text:
        return None
    now = _now_iso()
    event_nonce = turn_id if turn_id else (sequence if sequence is not None else time.time_ns())
    event = {
        "id": _stable_id("evt", role, event_nonce, _normalized(text)),
        "type": "message",
        "role": role,
        "content": text,
        "summary": _clip(text, 360),
        "keywords": _extract_keywords(text),
        "entities": _extract_entities(text),
        "semantic_tags": _semantic_tags(text),
        "created_at": now,
        "updated_at": now,
    }
    if turn_id:
        event["turn_id"] = turn_id
    return event

def _split_fact_sentences(content: str) -> list[str]:
    pieces = re.split(r"[\n。！？!?；;]+", content)
    sentences = [_clip(piece, MAX_FACT_TEXT_CHARS) for piece in pieces if piece.strip()]
    if _has_explicit_memory_marker(content) and len(content) <= MAX_FACT_TEXT_CHARS:
        sentences.insert(0, content)
    return sentences[:8]

def _starts_with_marker(text: str, markers: tuple[str, ...]) -> bool:
    stripped = text.strip(" ：:，,。；;!！?？")
    return any(stripped.startswith(marker) for marker in markers)

def _has_explicit_memory_marker(text: str) -> bool:
    return (
        _starts_with_marker(text, ("记住", "以后", "后续", "我希望", "我想", "我准备", "我们现在"))
        or "严格遵守" in text
        or "设计哲学" in text
    )

def _is_constraint_text(text: str) -> bool:
    stripped = text.strip()
    if "不能不" in stripped or "不会放弃" in stripped:
        return False
    if "严格遵守" in stripped:
        return True
    if _starts_with_marker(stripped, ("禁止", "不要", "不能", "不应该", "只需要", "暂时不用", "不开工")):
        return True
    if "必须" in stripped and (
        _starts_with_marker(stripped, ("必须", "后续必须", "以后必须", "我们必须"))
        or any(marker in stripped for marker in ("架构", "设计哲学", "边界", "输出", "格式", "工具"))
    ):
        return True
    return False

def _is_goal_text(text: str) -> bool:
    return _starts_with_marker(text, _GOAL_MARKERS) or any(marker in text for marker in ("目标是", "目标：", "计划", "准备"))

def _is_preference_text(text: str) -> bool:
    return _has_explicit_memory_marker(text) or any(marker in text for marker in ("偏好", "采用", "按这个", "按你说"))

def _is_deprecation_text(text: str) -> bool:
    if "不会放弃" in text or "不能不" in text:
        return False
    return any(marker in text for marker in _DEPRECATION_MARKERS)

def _looks_like_case_fact(text: str) -> bool:
    if re.search(r"^(我先|先看看|你好|您好|请问|能不能|可不可以)", text.strip()):
        return False
    patterns = (
        r"(?:甲方|乙方|甲公司|乙公司|对方|原告|被告|债务人|债权人|[\u4e00-\u9fffA-Za-z0-9]{1,16}公司).{0,40}"
        r"(?:未|没|没有|尚未|已经|仍未|拒绝|拖欠)?.{0,8}(?:付款|支付|付清|结清|交付|履行|还款|退款|赔偿|违约|收款)",
        r"(?:合同|协议).{0,40}(?:约定|签订|到期|解除|终止|还款|付款|交付|期限|标的|价款|违约金|履行)",
        r"(?:标的|金额|价款|货款|欠款|赔偿金额).{0,12}(?:是|为|约为|大概|改为|变成)?\s*[\d一二三四五六七八九十百千万亿〇零.]+",
        r"根据《[^》]{2,50}》第[一二三四五六七八九十百千万零〇\d]+条.{0,80}(?:构成|应当|可以|属于|承担|违约|责任)",
    )
    return any(re.search(pattern, text) for pattern in patterns)

def _classify_fact(text: str) -> tuple[str, float, float]:
    if _is_constraint_text(text):
        return "constraint", 0.95, 0.88
    if _looks_like_case_fact(text):
        return "fact", 0.74, 0.76
    if _is_goal_text(text):
        return "goal", 0.82, 0.8
    if _is_preference_text(text):
        return "preference", 0.78, 0.78
    return "fact", 0.5, 0.66

def _fact_domain_for_text(text: str, semantic_tags: list[str]) -> str | None:
    if re.search(r"(?:标的|金额|价款|货款|欠款|赔偿金额)", text):
        return "amount"
    if "payment_fact" in semantic_tags:
        return "payment"
    if "delivery_fact" in semantic_tags:
        return "delivery"
    if "contract_liability" in semantic_tags and re.search(r"(?:违约|责任|赔偿|构成|承担)", text):
        return "liability"
    if re.search(r"(?:合同|协议).{0,40}(?:期限|到期|解除|终止|签订|约定)", text):
        return "contract"
    return None

def _fact_key_for_text(
    text: str,
    kind: str,
    entities: list[str],
    semantic_tags: list[str],
    case_focus_id: str | None = None,
) -> str | None:
    if kind == "constraint":
        return None
    domain = _fact_domain_for_text(text, semantic_tags)
    if not domain:
        return None
    normalized_entities = [
        _normalized(entity)
        for entity in entities
        if _normalized(entity) and not entity.startswith("第") and not entity.startswith("《")
    ]
    if normalized_entities:
        return f"{domain}:{normalized_entities[0]}"
    if case_focus_id:
        return f"{domain}:case_focus:{case_focus_id}"
    return None

def _build_fact(
    event: dict[str, Any],
    sentence: str,
    kind: str,
    priority: float,
    confidence: float,
    case_focus_id: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    entities = _extract_entities(sentence)
    semantic_tags = _semantic_tags(sentence)
    fact = {
        "id": _stable_id("mem", kind, event.get("turn_id") or event["id"], _normalized(sentence)),
        "kind": kind,
        "text": sentence,
        "status": "active",
        "priority": priority,
        "confidence": confidence,
        "source_event_ids": [event["id"]],
        "created_at": now,
        "updated_at": now,
        "keywords": _extract_keywords(sentence),
        "entities": entities,
        "semantic_tags": semantic_tags,
    }
    fact_key = _fact_key_for_text(sentence, kind, entities, semantic_tags, case_focus_id)
    if fact_key:
        fact["fact_key"] = fact_key
    return fact

def _fact_candidates_from_user(event: dict[str, Any], case_focus_id: str | None = None) -> list[dict[str, Any]]:
    content = event["content"]
    if not (_has_explicit_memory_marker(content) or _is_constraint_text(content) or _is_goal_text(content) or _looks_like_case_fact(content)):
        return []

    facts = []
    for sentence in _split_fact_sentences(content):
        if not (
            _has_explicit_memory_marker(sentence)
            or _is_constraint_text(sentence)
            or _is_goal_text(sentence)
            or _looks_like_case_fact(sentence)
        ):
            continue
        kind, priority, confidence = _classify_fact(sentence)
        facts.append(_build_fact(event, sentence, kind, priority, confidence, case_focus_id))
    return facts

def _fact_candidates_from_assistant(event: dict[str, Any], case_focus_id: str | None = None) -> list[dict[str, Any]]:
    facts = []
    for sentence in _split_fact_sentences(event["content"]):
        if not _looks_like_case_fact(sentence):
            continue
        kind, priority, confidence = _classify_fact(sentence)
        if kind != "fact":
            continue
        facts.append(_build_fact(event, sentence, "fact", min(priority, 0.68), min(confidence, 0.72), case_focus_id))
    return facts

def _infer_focus_type(text: str) -> str:
    if _looks_like_case_fact(text) or any(marker in text for marker in ("案件", "争议", "诉求", "标的", "履行", "合同", "法条", "赔偿")):
        return "case"
    return "dialog"

def _focus_from_user(event: dict[str, Any]) -> dict[str, Any] | None:
    text = event["content"]
    if len(text) < 8:
        return None
    is_focus = _is_constraint_text(text) or _is_goal_text(text) or _has_explicit_memory_marker(text)
    case_focus = _looks_like_case_fact(text) or any(marker in text for marker in ("争议焦点", "核心问题", "诉求", "主线"))
    if not is_focus and not case_focus:
        return None
    kind, priority, _ = _classify_fact(text)
    priority = max(priority, 0.82 if kind in {"goal", "constraint"} else 0.72)
    now = _now_iso()
    label = "案件焦点" if case_focus else "当前任务"
    focus_text = f"{label}: {_clip(text, 420)}"
    return {
        "id": _stable_id("focus", _normalized(focus_text)),
        "text": focus_text,
        "status": "active",
        "priority": priority,
        "focus_type": "case" if case_focus else "dialog",
        "created_at": now,
        "updated_at": now,
        "keywords": _extract_keywords(focus_text),
        "entities": _extract_entities(focus_text),
        "semantic_tags": _semantic_tags(focus_text),
    }

def _append_unique(items: list[dict[str, Any]], item: dict[str, Any], similar_threshold: float = 0.9) -> dict[str, Any]:
    item_text = item.get("text") or item.get("content") or ""
    item_norm = _normalized(item_text)
    for existing in items:
        if existing.get("status") == "deprecated" and item.get("status") == "active" and existing.get("id") != item.get("id"):
            continue
        existing_text = existing.get("text") or existing.get("content") or ""
        if existing.get("id") == item.get("id") or SequenceMatcher(None, item_norm, _normalized(existing_text)).ratio() >= similar_threshold:
            existing.update(_prefer_newer(existing, item))
            if item.get("source_event_ids"):
                source_ids = list(dict.fromkeys(existing.get("source_event_ids", []) + item.get("source_event_ids", [])))
                existing["source_event_ids"] = source_ids[:8]
            return existing
    items.append(item)
    return item

def _mark_conflicts(snapshot: dict[str, Any], new_fact: dict[str, Any]) -> list[str]:
    explicit_deprecation = _is_deprecation_text(new_fact["text"])
    new_fact_key = new_fact.get("fact_key")
    new_tokens = set(new_fact.get("keywords", []))
    new_entities = set(new_fact.get("entities", []))
    new_features = _semantic_features(" ".join(new_fact.get("semantic_tags", [])) + " " + new_fact["text"])
    deprecated_ids: list[str] = []
    for fact in snapshot.get("facts", []):
        if fact.get("id") == new_fact.get("id") or fact.get("status") != "active":
            continue
        same_fact_key = new_fact_key and fact.get("fact_key") == new_fact_key
        overlap = _keyword_overlap(new_tokens, set(fact.get("keywords", [])))
        entity = _entity_overlap(new_entities, set(fact.get("entities", [])))
        semantic = _weighted_overlap(
            new_features,
            _semantic_features(" ".join(fact.get("semantic_tags", [])) + " " + fact.get("text", "")),
        )
        similar_text = SequenceMatcher(None, _normalized(new_fact["text"]), _normalized(fact.get("text", ""))).ratio() >= 0.9
        if same_fact_key or (explicit_deprecation and (overlap >= 0.35 or (entity > 0 and semantic >= 0.2) or similar_text)):
            fact["status"] = "deprecated"
            fact["superseded_by"] = new_fact["id"]
            fact["updated_at"] = _now_iso()
            deprecated_ids.append(str(fact["id"]))
    return deprecated_ids

def _active_case_focus_id(snapshot: dict[str, Any]) -> str | None:
    active_case_focus = [
        item for item in snapshot.get("focus", [])
        if item.get("status") != "deprecated" and item.get("focus_type") == "case"
    ]
    if not active_case_focus:
        return None
    active_case_focus.sort(
        key=lambda item: (float(item.get("priority", 0)), _timestamp(item.get("updated_at"))),
        reverse=True,
    )
    return str(active_case_focus[0].get("id") or "") or None

def _observe_messages(snapshot: dict[str, Any], messages: list[dict[str, Any]], turn_id: str | None = None) -> dict[str, Any]:
    if not isinstance(messages, list):
        return snapshot
    for sequence, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        event = _event_from_message(message.get("role"), message.get("content"), turn_id=turn_id, sequence=sequence)
        if not event:
            continue
        _append_unique(snapshot["events"], event, similar_threshold=1.01)
        if event["role"] == "user":
            case_focus_id = _active_case_focus_id(snapshot)
            focus = _focus_from_user(event)
            if focus:
                stored_focus = _append_unique(snapshot["focus"], focus, similar_threshold=0.86)
                if stored_focus.get("focus_type") == "case":
                    case_focus_id = str(stored_focus.get("id") or "") or case_focus_id
            for fact in _fact_candidates_from_user(event, case_focus_id):
                _mark_conflicts(snapshot, fact)
                _append_unique(snapshot["facts"], fact, similar_threshold=0.88)
        elif event["role"] == "assistant":
            case_focus_id = _active_case_focus_id(snapshot)
            for fact in _fact_candidates_from_assistant(event, case_focus_id):
                _mark_conflicts(snapshot, fact)
                _append_unique(snapshot["facts"], fact, similar_threshold=0.88)
    snapshot["updated_at"] = _now_iso()
    return snapshot

__all__ = [name for name in globals() if not name.startswith("__")]
