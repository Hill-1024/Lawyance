from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

from .state import *

def _looks_like_prompt_override(text: Any) -> bool:
    value = _strip_message_noise(text)
    if not value:
        return False
    if _PROMPT_DISCLOSURE_RE.search(value) and not _PROMPT_DISCLOSURE_NEGATION_RE.search(value):
        return True
    return any(re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL) for pattern in _PROMPT_OVERRIDE_PATTERNS)

def _context_memory_text(text: Any, limit: int) -> str:
    value = _clip(text, limit)
    if _looks_like_prompt_override(value):
        return ""
    return value.replace("<", "&lt;").replace(">", "&gt;")

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
    closing_tag = "</conversation_memory>"
    if value.startswith("<conversation_memory>"):
        suffix = "\n...\n" + closing_tag
        if limit > len(suffix):
            return value[: limit - len(suffix)].rstrip() + suffix
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
    candidates = []
    for keyword in keywords:
        if keyword and keyword not in seen:
            seen.add(keyword)
            candidates.append(keyword)
    if len(candidates) <= MAX_KEYWORDS:
        return candidates
    stride = math.ceil(len(candidates) / MAX_KEYWORDS)
    sampled = candidates[::stride][:MAX_KEYWORDS]
    if len(sampled) < MAX_KEYWORDS:
        sampled_set = set(sampled)
        for keyword in candidates:
            if keyword in sampled_set:
                continue
            sampled.append(keyword)
            sampled_set.add(keyword)
            if len(sampled) >= MAX_KEYWORDS:
                break
    return sampled[:MAX_KEYWORDS]

def _extract_entities(text: Any) -> list[str]:
    source = _strip_message_noise(text)
    seen = set()
    entities = []
    for match in _ENTITY_RE.findall(source):
        entity = _clip(match, 80)
        if not entity:
            continue
        if entity.endswith("公司"):
            for separator in ("：", ":", "是", "为"):
                if separator in entity:
                    entity = entity.rsplit(separator, 1)[-1]
                    break
        if entity.isascii():
            if entity.upper() in _ASCII_ENTITY_STOPWORDS:
                continue
            if len(entity) < 3 or not (entity.isupper() or any(ch.isdigit() or ch in "._-" for ch in entity)):
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

def _clamp(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return lower
    return max(lower, min(number, upper))

__all__ = [name for name in globals() if not name.startswith("__")]
