from __future__ import annotations

import copy
import hashlib
import math
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

MEMORY_VERSION = 1
MAX_EVENTS = 200
MAX_FACTS = 80
MAX_FOCUS = 16
MAX_KEYWORDS = 64
MAX_EVENT_CONTENT_CHARS = 3000
MAX_FACT_TEXT_CHARS = 600
MAX_CONTEXT_CHARS = 2800
MAX_ENTITIES = 32
MAX_SEMANTIC_TAGS = 24

_CONVERSATION_CACHE: dict[str, dict[str, Any]] = {}

_ASCII_TOKEN_RE = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_ENTITY_RE = re.compile(
    r"(?:[\u4e00-\u9fffA-Za-z0-9]{1,16}(?:公司|法院|律所|银行|学校|平台|部门|系统|模块|工具|法库|数据库))"
    r"|(?:《[^》]{2,50}》第[一二三四五六七八九十百千万零〇\d]+条)"
    r"|(?:第[一二三四五六七八九十百千万零〇\d]+条)"
    r"|(?:[A-Za-z][A-Za-z0-9_.-]{1,32})"
)
_LEADING_TIME_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}[^\]]*]\s*")
_SPACE_RE = re.compile(r"\s+")

_FACT_MARKERS = (
    "记住",
    "以后",
    "后续",
    "我希望",
    "我想",
    "我准备",
    "我们现在",
    "目标",
    "按",
    "采用",
    "严格遵守",
    "必须",
    "禁止",
    "不要",
    "不用",
    "暂时不用",
    "只需要",
    "先",
    "不开工",
    "偏好",
    "架构",
    "设计哲学",
)
_CONSTRAINT_MARKERS = (
    "严格遵守",
    "必须",
    "禁止",
    "不要",
    "不能",
    "不应该",
    "只需要",
    "暂时不用",
    "不开工",
)
_GOAL_MARKERS = ("我准备", "希望", "目标", "我们现在", "按你说", "按这个", "来做")
_DEPRECATION_MARKERS = ("不再", "不用", "放弃", "取消", "改为", "替换为", "不要再")
_SEMANTIC_LEXICON: dict[str, tuple[str, ...]] = {
    "memory_scope": (
        "记忆", "长期", "对话级", "用户级", "全局", "持久", "缓存", "用户侧", "服务端", "本地",
        "同步", "快照", "存储", "历史", "上下文",
    ),
    "attention_control": (
        "注意力", "聚焦", "焦点", "稳定", "集中", "常驻", "每轮", "自动注入", "不会忘", "想起",
        "遗漏", "关注", "提醒", "保障", "保持",
    ),
    "retrieval": (
        "检索", "召回", "查询", "搜索", "模糊", "语义", "向量", "embedding", "rag", "关键词",
        "匹配", "相关", "找回", "联想", "深查",
    ),
    "architecture_boundary": (
        "强解耦", "高复用", "黑箱", "边界", "跨模块", "直接访问", "请求转发", "路由", "中间件",
        "mcps", "模块", "组件", "隔离", "总线", "调度", "入口", "工具转发", "访问工具",
    ),
    "workflow_plan": (
        "方案", "技术方案", "不开工", "先讨论", "实现", "自测", "完成", "继续", "修复",
        "验证", "测试", "重构", "上线", "本地运行",
    ),
    "undo_revision": (
        "撤回", "重发", "修改", "改为", "替换", "修正", "重建", "清空", "删除", "回滚",
        "旧事实", "新事实", "更改", "否定",
    ),
    "payment_fact": (
        "付款", "支付", "付清", "结清", "款项", "价款", "货款", "欠款", "未付", "尚未付款",
        "已经付款", "转账", "收款",
    ),
    "delivery_fact": (
        "交付", "标的物", "履行", "移交", "交货", "收货", "验收", "未交付", "尚未交付",
        "已经交付", "给付",
    ),
    "contract_liability": (
        "合同", "违约", "责任", "民法典", "法条", "案例", "法律", "条文", "第五百七十七条",
        "赔偿", "继续履行", "补救措施",
    ),
    "ocp": (
        "ocp", "输出审查", "格式审查", "信源", "超时", "降级", "保留原文", "后处理",
    ),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _timestamp(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _clip(text: Any, limit: int) -> str:
    value = "" if text is None else str(text)
    value = _SPACE_RE.sub(" ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _clip_context(text: str, limit: int) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _strip_message_noise(content: Any) -> str:
    text = _clip(content, MAX_EVENT_CONTENT_CHARS)
    text = _LEADING_TIME_RE.sub("", text)
    return text.strip()


def _normalized(text: Any) -> str:
    value = "" if text is None else str(text)
    value = _LEADING_TIME_RE.sub("", value)
    value = value.lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value


def _stable_id(prefix: str, *parts: Any) -> str:
    hasher = hashlib.sha1()
    for part in parts:
        hasher.update(str(part).encode("utf-8", errors="ignore"))
        hasher.update(b"\x00")
    return f"{prefix}_{hasher.hexdigest()[:16]}"


def _extract_keywords(text: Any) -> list[str]:
    normalized = _strip_message_noise(text).lower()
    keywords: list[str] = []

    for token in _ASCII_TOKEN_RE.findall(normalized):
        keywords.append(token)

    for match in _CJK_RE.findall(normalized):
        if len(match) <= 8:
            keywords.append(match)
        keywords.extend(match[i : i + 1] for i in range(len(match)))
        keywords.extend(match[i : i + 2] for i in range(max(len(match) - 1, 0)))
        if len(match) >= 3:
            keywords.extend(match[i : i + 3] for i in range(len(match) - 2))

    seen = set()
    result = []
    for keyword in keywords:
        if keyword and keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
        if len(result) >= MAX_KEYWORDS:
            break
    return result


def _extract_entities(text: Any) -> list[str]:
    source = _strip_message_noise(text)
    seen = set()
    entities = []
    for match in _ENTITY_RE.findall(source):
        entity = _clip(match, 80)
        if not entity:
            continue
        normalized = entity.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        entities.append(entity)
        if len(entities) >= MAX_ENTITIES:
            break
    return entities


def _semantic_features(text: Any) -> dict[str, float]:
    normalized = _strip_message_noise(text).lower()
    compact = _normalized(normalized)
    features: dict[str, float] = {}
    if not compact:
        return features

    for tag, aliases in _SEMANTIC_LEXICON.items():
        weight = 0.0
        if tag.lower() in normalized:
            weight += 1.0
        for alias in aliases:
            alias_norm = _normalized(alias)
            if not alias_norm:
                continue
            if alias.lower() in normalized or alias_norm in compact:
                weight += 1.0 + min(len(alias_norm) / 12, 0.8)
        if weight:
            features[tag] = round(min(weight, 4.0), 4)
    return features


def _semantic_tags(text: Any) -> list[str]:
    features = _semantic_features(text)
    return [
        tag
        for tag, _ in sorted(features.items(), key=lambda item: item[1], reverse=True)[:MAX_SEMANTIC_TAGS]
    ]


def _sanitize_entities(raw_entities: Any, fallback_text: str) -> list[str]:
    if isinstance(raw_entities, list):
        seen = set()
        entities = []
        for item in raw_entities:
            entity = _clip(item, 80)
            entity_key = entity.lower()
            if entity and entity_key not in seen:
                seen.add(entity_key)
                entities.append(entity)
            if len(entities) >= MAX_ENTITIES:
                break
        if entities:
            return entities
    return _extract_entities(fallback_text)


def _sanitize_semantic_tags(raw_tags: Any, fallback_text: str) -> list[str]:
    allowed = set(_SEMANTIC_LEXICON)
    if isinstance(raw_tags, list):
        seen = set()
        tags = []
        for item in raw_tags:
            tag = str(item)
            if tag in allowed and tag not in seen:
                seen.add(tag)
                tags.append(tag)
            if len(tags) >= MAX_SEMANTIC_TAGS:
                break
        if tags:
            return tags
    return _semantic_tags(fallback_text)


def _sanitize_keywords(raw_keywords: Any, fallback_text: str) -> list[str]:
    if isinstance(raw_keywords, list):
        seen = set()
        keywords = []
        for item in raw_keywords:
            keyword = _clip(item, 80)
            if keyword and keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
            if len(keywords) >= MAX_KEYWORDS:
                break
        if keywords:
            return keywords
    return _extract_keywords(fallback_text)


def _keyword_overlap(query_tokens: set[str], item_tokens: set[str]) -> float:
    if not query_tokens or not item_tokens:
        return 0.0
    return len(query_tokens & item_tokens) / math.sqrt(len(query_tokens) * len(item_tokens))


def _weighted_overlap(query_features: dict[str, float], item_features: dict[str, float]) -> float:
    if not query_features or not item_features:
        return 0.0
    shared = set(query_features) & set(item_features)
    if not shared:
        return 0.0
    numerator = sum(min(query_features[tag], item_features[tag]) for tag in shared)
    query_norm = math.sqrt(sum(value * value for value in query_features.values()))
    item_norm = math.sqrt(sum(value * value for value in item_features.values()))
    if not query_norm or not item_norm:
        return 0.0
    return numerator / math.sqrt(query_norm * item_norm)


def _entity_overlap(query_entities: set[str], item_entities: set[str]) -> float:
    if not query_entities or not item_entities:
        return 0.0
    query_norms = {_normalized(entity) for entity in query_entities if _normalized(entity)}
    item_norms = {_normalized(entity) for entity in item_entities if _normalized(entity)}
    if not query_norms or not item_norms:
        return 0.0
    matches = 0
    for query_entity in query_norms:
        if any(query_entity in item_entity or item_entity in query_entity for item_entity in item_norms):
            matches += 1
    return matches / math.sqrt(len(query_norms) * len(item_norms))


def _blank_snapshot() -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": MEMORY_VERSION,
        "scope": {
            "type": "conversation",
            "future_user_scope": None,
        },
        "events": [],
        "facts": [],
        "focus": [],
        "updated_at": now,
        "last_synced_at": now,
    }


def _sanitize_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    role = raw.get("role")
    if role not in {"user", "assistant", "system"}:
        return None
    content = _strip_message_noise(raw.get("content") or raw.get("summary") or "")
    if not content:
        return None
    created_at = raw.get("created_at") if isinstance(raw.get("created_at"), str) else _now_iso()
    event = {
        "id": str(raw.get("id") or _stable_id("evt", role, content)),
        "type": str(raw.get("type") or "message"),
        "role": role,
        "content": content,
        "summary": _clip(raw.get("summary") or content, 360),
        "keywords": _sanitize_keywords(raw.get("keywords"), content),
        "entities": _sanitize_entities(raw.get("entities"), content),
        "semantic_tags": _sanitize_semantic_tags(raw.get("semantic_tags"), content),
        "created_at": created_at,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else created_at,
    }
    if raw.get("turn_id"):
        event["turn_id"] = str(raw["turn_id"])
    return event


def _sanitize_fact(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = _clip(raw.get("text") or raw.get("content") or "", MAX_FACT_TEXT_CHARS)
    if not text:
        return None
    now = _now_iso()
    kind = str(raw.get("kind") or "fact")
    status = str(raw.get("status") or "active")
    if status not in {"active", "deprecated"}:
        status = "active"
    source_event_ids = raw.get("source_event_ids")
    if not isinstance(source_event_ids, list):
        source_event_ids = []
    fact = {
        "id": str(raw.get("id") or _stable_id("mem", kind, text)),
        "kind": kind,
        "text": text,
        "status": status,
        "priority": float(raw.get("priority", 0.5) or 0.5),
        "confidence": float(raw.get("confidence", 0.75) or 0.75),
        "source_event_ids": [str(item) for item in source_event_ids[:8]],
        "created_at": raw.get("created_at") if isinstance(raw.get("created_at"), str) else now,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else now,
        "keywords": _sanitize_keywords(raw.get("keywords"), text),
        "entities": _sanitize_entities(raw.get("entities"), text),
        "semantic_tags": _sanitize_semantic_tags(raw.get("semantic_tags"), text),
    }
    if raw.get("superseded_by"):
        fact["superseded_by"] = str(raw["superseded_by"])
    return fact


def _sanitize_focus(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = _clip(raw.get("text") or raw.get("content") or "", MAX_FACT_TEXT_CHARS)
    if not text:
        return None
    now = _now_iso()
    return {
        "id": str(raw.get("id") or _stable_id("focus", text)),
        "text": text,
        "status": "active",
        "priority": float(raw.get("priority", 0.6) or 0.6),
        "created_at": raw.get("created_at") if isinstance(raw.get("created_at"), str) else now,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else now,
        "keywords": _sanitize_keywords(raw.get("keywords"), text),
        "entities": _sanitize_entities(raw.get("entities"), text),
        "semantic_tags": _sanitize_semantic_tags(raw.get("semantic_tags"), text),
    }


def _sanitize_snapshot(snapshot: Any) -> dict[str, Any]:
    clean = _blank_snapshot()
    if not isinstance(snapshot, dict):
        return clean

    scope = snapshot.get("scope")
    if isinstance(scope, dict):
        clean["scope"] = {
            "type": "conversation",
            "future_user_scope": scope.get("future_user_scope"),
        }
    if snapshot.get("conversation_id"):
        clean["conversation_id"] = str(snapshot["conversation_id"])

    raw_events = snapshot.get("events") if isinstance(snapshot.get("events"), list) else []
    raw_facts = snapshot.get("facts") if isinstance(snapshot.get("facts"), list) else []
    raw_focus = snapshot.get("focus") if isinstance(snapshot.get("focus"), list) else []
    events = [_sanitize_event(item) for item in raw_events]
    facts = [_sanitize_fact(item) for item in raw_facts]
    focus = [_sanitize_focus(item) for item in raw_focus]
    clean["events"] = [item for item in events if item]
    clean["facts"] = [item for item in facts if item]
    clean["focus"] = [item for item in focus if item]
    clean["updated_at"] = snapshot.get("updated_at") if isinstance(snapshot.get("updated_at"), str) else clean["updated_at"]
    clean["last_synced_at"] = snapshot.get("last_synced_at") if isinstance(snapshot.get("last_synced_at"), str) else clean["last_synced_at"]
    return _prune_snapshot(clean)


def _prefer_newer(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if _timestamp(incoming.get("updated_at")) >= _timestamp(existing.get("updated_at")):
        return incoming
    return existing


def _merge_items(base_items: list[dict[str, Any]], incoming_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in base_items + incoming_items:
        item_id = str(item.get("id") or _stable_id("item", item.get("text") or item.get("content") or ""))
        if item_id in merged:
            merged[item_id] = _prefer_newer(merged[item_id], item)
        else:
            merged[item_id] = item
    return list(merged.values())


def _merge_snapshots(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base or _blank_snapshot())
    incoming = incoming or _blank_snapshot()
    result["version"] = MEMORY_VERSION
    if incoming.get("conversation_id"):
        result["conversation_id"] = incoming["conversation_id"]
    result["scope"] = {
        "type": "conversation",
        "future_user_scope": incoming.get("scope", {}).get("future_user_scope"),
    }
    result["events"] = _merge_items(result.get("events", []), incoming.get("events", []))
    result["facts"] = _merge_items(result.get("facts", []), incoming.get("facts", []))
    result["focus"] = _merge_items(result.get("focus", []), incoming.get("focus", []))
    result["updated_at"] = max(
        result.get("updated_at") or "",
        incoming.get("updated_at") or "",
    )
    result["last_synced_at"] = _now_iso()
    return _prune_snapshot(result)


def _snapshot_shell_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = _blank_snapshot()
    if snapshot.get("conversation_id"):
        result["conversation_id"] = snapshot["conversation_id"]
    result["scope"] = {
        "type": "conversation",
        "future_user_scope": snapshot.get("scope", {}).get("future_user_scope"),
    }
    return result


def _event_from_message(role: str, content: Any, turn_id: str | None = None) -> dict[str, Any] | None:
    if role not in {"user", "assistant", "system"}:
        return None
    text = _strip_message_noise(content)
    if not text:
        return None
    if role == "assistant" and "您好，我是 **Lawver**" in text:
        return None
    now = _now_iso()
    event = {
        "id": _stable_id("evt", role, _normalized(text)),
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
    if any(marker in content for marker in _FACT_MARKERS) and len(content) <= MAX_FACT_TEXT_CHARS:
        sentences.insert(0, content)
    return sentences[:8]


def _classify_fact(text: str) -> tuple[str, float, float]:
    if any(marker in text for marker in _CONSTRAINT_MARKERS):
        return "constraint", 0.95, 0.88
    if any(marker in text for marker in _GOAL_MARKERS):
        return "goal", 0.82, 0.8
    if any(marker in text for marker in _FACT_MARKERS):
        return "preference", 0.78, 0.78
    return "fact", 0.5, 0.66


def _fact_candidates_from_user(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = event["content"]
    if not any(marker in content for marker in _FACT_MARKERS):
        return []

    facts = []
    for sentence in _split_fact_sentences(content):
        if not any(marker in sentence for marker in _FACT_MARKERS):
            continue
        kind, priority, confidence = _classify_fact(sentence)
        now = _now_iso()
        facts.append(
            {
                "id": _stable_id("mem", kind, _normalized(sentence)),
                "kind": kind,
                "text": sentence,
                "status": "active",
                "priority": priority,
                "confidence": confidence,
                "source_event_ids": [event["id"]],
                "created_at": now,
                "updated_at": now,
                "keywords": _extract_keywords(sentence),
                "entities": _extract_entities(sentence),
                "semantic_tags": _semantic_tags(sentence),
            }
        )
    return facts


def _focus_from_user(event: dict[str, Any]) -> dict[str, Any] | None:
    text = event["content"]
    if len(text) < 8:
        return None
    kind, priority, _ = _classify_fact(text)
    priority = max(priority, 0.68)
    now = _now_iso()
    label = "当前任务" if kind in {"goal", "constraint", "preference"} else "最近用户关注"
    focus_text = f"{label}: {_clip(text, 420)}"
    return {
        "id": _stable_id("focus", _normalized(focus_text)),
        "text": focus_text,
        "status": "active",
        "priority": priority,
        "created_at": now,
        "updated_at": now,
        "keywords": _extract_keywords(focus_text),
        "entities": _extract_entities(focus_text),
        "semantic_tags": _semantic_tags(focus_text),
    }


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any], similar_threshold: float = 0.9) -> None:
    item_text = item.get("text") or item.get("content") or ""
    item_norm = _normalized(item_text)
    for existing in items:
        existing_text = existing.get("text") or existing.get("content") or ""
        if existing.get("id") == item.get("id") or SequenceMatcher(None, item_norm, _normalized(existing_text)).ratio() >= similar_threshold:
            existing.update(_prefer_newer(existing, item))
            if item.get("source_event_ids"):
                source_ids = list(dict.fromkeys(existing.get("source_event_ids", []) + item.get("source_event_ids", [])))
                existing["source_event_ids"] = source_ids[:8]
            return
    items.append(item)


def _mark_conflicts(snapshot: dict[str, Any], new_fact: dict[str, Any]) -> None:
    if not any(marker in new_fact["text"] for marker in _DEPRECATION_MARKERS):
        return
    new_tokens = set(new_fact.get("keywords", []))
    new_entities = set(new_fact.get("entities", []))
    new_features = _semantic_features(" ".join(new_fact.get("semantic_tags", [])) + " " + new_fact["text"])
    for fact in snapshot.get("facts", []):
        if fact.get("id") == new_fact.get("id") or fact.get("status") != "active":
            continue
        overlap = _keyword_overlap(new_tokens, set(fact.get("keywords", [])))
        entity = _entity_overlap(new_entities, set(fact.get("entities", [])))
        semantic = _weighted_overlap(
            new_features,
            _semantic_features(" ".join(fact.get("semantic_tags", [])) + " " + fact.get("text", "")),
        )
        if overlap >= 0.35 or (entity > 0 and semantic >= 0.2):
            fact["status"] = "deprecated"
            fact["superseded_by"] = new_fact["id"]
            fact["updated_at"] = _now_iso()


def _observe_messages(snapshot: dict[str, Any], messages: list[dict[str, Any]], turn_id: str | None = None) -> dict[str, Any]:
    if not isinstance(messages, list):
        return snapshot
    for message in messages:
        if not isinstance(message, dict):
            continue
        event = _event_from_message(message.get("role"), message.get("content"), turn_id=turn_id)
        if not event:
            continue
        _append_unique(snapshot["events"], event)
        if event["role"] == "user":
            focus = _focus_from_user(event)
            if focus:
                _append_unique(snapshot["focus"], focus, similar_threshold=0.86)
            for fact in _fact_candidates_from_user(event):
                _mark_conflicts(snapshot, fact)
                _append_unique(snapshot["facts"], fact, similar_threshold=0.88)
    snapshot["updated_at"] = _now_iso()
    return _prune_snapshot(snapshot)


def _prune_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot["events"] = sorted(
        snapshot.get("events", []),
        key=lambda item: (_timestamp(item.get("updated_at")), _timestamp(item.get("created_at"))),
        reverse=True,
    )[:MAX_EVENTS]
    snapshot["facts"] = sorted(
        snapshot.get("facts", []),
        key=lambda item: (item.get("status") == "active", float(item.get("priority", 0)), _timestamp(item.get("updated_at"))),
        reverse=True,
    )[:MAX_FACTS]
    snapshot["focus"] = sorted(
        snapshot.get("focus", []),
        key=lambda item: (_timestamp(item.get("updated_at")), float(item.get("priority", 0))),
        reverse=True,
    )[:MAX_FOCUS]
    snapshot["version"] = MEMORY_VERSION
    return snapshot


def _rank_items(snapshot: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    query_text = _strip_message_noise(query)
    query_norm = _normalized(query_text)
    query_tokens = set(_extract_keywords(query_text))
    query_entities = set(_extract_entities(query_text))
    query_features = _semantic_features(query_text)
    now = time.time()
    candidates: list[dict[str, Any]] = []

    def add_candidate(kind: str, item: dict[str, Any], text_key: str) -> None:
        if item.get("status") == "deprecated":
            return
        text = item.get(text_key) or ""
        item_tokens = set(item.get("keywords") or _extract_keywords(text))
        item_entities = set(item.get("entities") or _extract_entities(text))
        item_features = _semantic_features(" ".join(item.get("semantic_tags", [])) + " " + text)
        lexical = _keyword_overlap(query_tokens, item_tokens)
        semantic = _weighted_overlap(query_features, item_features)
        entity = _entity_overlap(query_entities, item_entities)
        text_norm = _normalized(text)
        fuzzy = SequenceMatcher(None, query_norm[:600], text_norm[:600]).ratio() if query_norm and text_norm else 0.0
        substring = 1.0 if query_norm and (query_norm in text_norm or text_norm in query_norm) else 0.0
        age_hours = max((now - _timestamp(item.get("updated_at"))) / 3600, 0)
        recency = 1 / (1 + age_hours / 72)
        priority = float(item.get("priority", 0.45) or 0.45)
        pinned = (
            kind == "focus"
            or item.get("kind") == "constraint"
            or priority >= 0.92
        )
        kind_boost = {"fact": 0.35, "focus": 0.55, "event": 0.15}.get(kind, 0.0)
        score = (
            lexical * 2.6
            + fuzzy * 0.9
            + substring * 1.6
            + semantic * 3.1
            + entity * 2.2
            + recency * 0.3
            + priority
            + kind_boost
            + (1.2 if pinned else 0.0)
        )
        routes = []
        if pinned:
            routes.append("pinned")
        if semantic >= 0.2:
            routes.append("semantic")
        if entity > 0:
            routes.append("entity")
        if lexical >= 0.08 or fuzzy >= 0.22 or substring:
            routes.append("lexical")
        if recency >= 0.96 and query_text:
            routes.append("recency")

        has_query_route = any(route in routes for route in ("semantic", "entity", "lexical"))
        should_include = pinned or (query_text and has_query_route and score >= 0.75)
        if should_include:
            candidates.append(
                {
                    "kind": kind,
                    "score": round(score, 4),
                    "text": _clip(text, 420),
                    "source_id": item.get("id"),
                    "memory_kind": item.get("kind"),
                    "updated_at": item.get("updated_at"),
                    "routes": routes,
                    "signals": {
                        "semantic": round(semantic, 4),
                        "entity": round(entity, 4),
                        "lexical": round(max(lexical, fuzzy, substring), 4),
                        "recency": round(recency, 4),
                    },
                }
            )

    for fact in snapshot.get("facts", []):
        add_candidate("fact", fact, "text")
    for focus in snapshot.get("focus", []):
        add_candidate("focus", focus, "text")
    for event in snapshot.get("events", []):
        add_candidate("event", event, "summary")

    candidates.sort(key=lambda item: item["score"], reverse=True)
    seen = set()
    result = []
    for item in candidates:
        norm = _normalized(item["text"])
        if norm in seen:
            continue
        seen.add(norm)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _context_lines(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"{title}:"] + [f"- {item}" for item in items]


def _build_context_packet(snapshot: dict[str, Any], query: str, retrieved: list[dict[str, Any]]) -> str:
    active_facts = [fact for fact in snapshot.get("facts", []) if fact.get("status") == "active"]
    constraints = [
        _clip(fact["text"], 280)
        for fact in sorted(active_facts, key=lambda item: (item.get("kind") == "constraint", item.get("priority", 0)), reverse=True)
        if fact.get("kind") == "constraint"
    ][:5]
    focus_items = [_clip(item["text"], 280) for item in snapshot.get("focus", [])[:4]]
    retrieved_texts = []
    known = {_normalized(item) for item in constraints + focus_items}
    for item in retrieved:
        norm = _normalized(item["text"])
        if norm and norm not in known:
            known.add(norm)
            retrieved_texts.append(item["text"])
        if len(retrieved_texts) >= 6:
            break

    if not constraints and not focus_items and not retrieved_texts:
        return ""

    lines = [
        "<conversation_memory>",
        "作用域: 当前对话级记忆。持久源在用户侧，服务端仅使用活跃缓存；这些内容不是用户级全局画像。",
    ]
    lines.extend(_context_lines("当前焦点", focus_items))
    lines.extend(_context_lines("高优先级约束", constraints))
    lines.extend(_context_lines("相关长期记忆", retrieved_texts))
    lines.extend(
        [
            "使用规则:",
            "- 每轮必须优先检查当前焦点和高优先级约束，不能依赖模型主动调用记忆工具才想起。",
            "- 如果本轮用户明确修改或否定旧记忆，以本轮用户消息为准，并在回合结束后更新对话记忆。",
            "</conversation_memory>",
        ]
    )
    context = "\n".join(lines)
    return _clip_context(context, MAX_CONTEXT_CHARS)


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    clean = _prune_snapshot(copy.deepcopy(snapshot))
    clean["last_synced_at"] = _now_iso()
    return clean


def sync_conversation_memory(scope: str, snapshot: Any = None, messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    incoming = _sanitize_snapshot(snapshot)
    if messages is not None:
        merged = _snapshot_shell_from_snapshot(incoming)
        if messages:
            merged = _observe_messages(merged, messages)
        sync_mode = "rebuild"
    else:
        current = _CONVERSATION_CACHE.get(scope) or _blank_snapshot()
        merged = _merge_snapshots(current, incoming)
        sync_mode = "merge"
    merged["last_synced_at"] = _now_iso()
    _CONVERSATION_CACHE[scope] = merged
    print(
        f"[记忆系统] sync scope={scope} mode={sync_mode} "
        f"messages={len(messages) if messages is not None else 'none'} "
        f"events={len(merged.get('events', []))} facts={len(merged.get('facts', []))} focus={len(merged.get('focus', []))}"
    )
    return {
        "status": "success",
        "memory": _public_snapshot(merged),
    }


def retrieve_conversation_memory(scope: str, query: str, limit: int = 8) -> dict[str, Any]:
    snapshot = _CONVERSATION_CACHE.get(scope) or _blank_snapshot()
    try:
        resolved_limit = max(1, min(int(limit), 12))
    except (TypeError, ValueError):
        resolved_limit = 8
    retrieved = _rank_items(snapshot, query or "", resolved_limit)
    context = _build_context_packet(snapshot, query or "", retrieved)
    routes = sorted({route for item in retrieved for route in item.get("routes", [])})
    print(
        f"[记忆系统] retrieve scope={scope} query={_clip(_strip_message_noise(query or ''), 80)} "
        f"items={len(retrieved)} routes={','.join(routes) if routes else 'none'}"
    )
    return {
        "status": "success",
        "context": context,
        "items": retrieved,
        "memory": _public_snapshot(snapshot),
    }


def remember_conversation_turn(scope: str, user_message: str, assistant_message: str) -> dict[str, Any]:
    snapshot = _CONVERSATION_CACHE.get(scope) or _blank_snapshot()
    turn_id = _stable_id("turn", time.time(), user_message[:120])
    snapshot = _observe_messages(
        snapshot,
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message},
        ],
        turn_id=turn_id,
    )
    snapshot["last_synced_at"] = _now_iso()
    _CONVERSATION_CACHE[scope] = snapshot
    print(
        f"[记忆系统] remember scope={scope} "
        f"events={len(snapshot.get('events', []))} facts={len(snapshot.get('facts', []))} focus={len(snapshot.get('focus', []))}"
    )
    retrieved = _rank_items(snapshot, user_message or "", 8)
    return {
        "status": "success",
        "memory": _public_snapshot(snapshot),
        "context": _build_context_packet(snapshot, user_message or "", retrieved),
    }


def clear_conversation_memory(scope: str) -> dict[str, Any]:
    _CONVERSATION_CACHE.pop(scope, None)
    return {"status": "success"}
