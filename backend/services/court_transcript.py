"""
模块描述：模拟法庭公开庭审记录滚动摘要与上下文裁剪。
"""

from __future__ import annotations

from typing import Any

from context_usage import estimate_text_tokens, trim_text_to_token_budget


MAX_RECENT_EVENTS = 16
SUMMARY_EVENT_THRESHOLD = 20
SUMMARY_TOKEN_BUDGET = 14000

SPEAKER_LABELS = {
    "judge": "法官",
    "opponent": "对方律师/公诉方",
    "reviewer": "复盘员",
    "user": "用户方",
    "system": "系统",
}


def speaker_label(speaker: str | None) -> str:
    return SPEAKER_LABELS.get(str(speaker or ""), str(speaker or "未知"))


def format_public_event(event: dict[str, Any]) -> str:
    phase = str(event.get("phase") or "unknown")
    speaker = speaker_label(event.get("speaker"))
    content = str(event.get("content") or "").strip()
    event_type = str(event.get("type") or "speech")
    return f"[{phase}] {speaker} ({event_type}): {content}"


def prepare_public_transcript(
    public_summary: str,
    public_events: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    events = [event for event in public_events if isinstance(event, dict)]
    if len(events) <= SUMMARY_EVENT_THRESHOLD:
        return str(public_summary or ""), events

    older = events[:-MAX_RECENT_EVENTS]
    recent = events[-MAX_RECENT_EVENTS:]
    older_text = "\n".join(format_public_event(event) for event in older)
    existing_summary = str(public_summary or "").strip()
    merged = "\n".join(part for part in [existing_summary, "【已归档庭审记录】", older_text] if part)
    if estimate_text_tokens(merged) > SUMMARY_TOKEN_BUDGET:
        merged = trim_text_to_token_budget(merged, SUMMARY_TOKEN_BUDGET)
    return merged, recent


def render_public_context(public_summary: str, recent_events: list[dict[str, Any]]) -> str:
    parts = []
    if public_summary.strip():
        parts.append("【公开庭审摘要】\n" + public_summary.strip())
    if recent_events:
        parts.append("【近期公开庭审记录】\n" + "\n".join(format_public_event(event) for event in recent_events))
    return "\n\n".join(parts).strip() or "暂无公开庭审记录。"


__all__ = ["format_public_event", "prepare_public_transcript", "render_public_context", "speaker_label"]
