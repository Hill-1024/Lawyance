"""
模块描述：模拟法庭公开庭审记录滚动摘要与上下文裁剪。
"""

from __future__ import annotations

from typing import Any

from context_usage import estimate_text_tokens


MAX_RECENT_EVENTS = 16
SUMMARY_EVENT_THRESHOLD = 20
SUMMARY_TOKEN_BUDGET = 14000
ARCHIVE_MARKER = "【已归档庭审记录】"

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


def _trim_head_to_token_budget(text: str, token_budget: int) -> str:
    """保**尾**截断：返回不超过预算的最大后缀（与 trim_text_to_token_budget 相反）。

    归档摘要里越靠后越新：紧贴 recent 窗口的归档必须留在场，被裁的只能是最旧段落。
    """
    if token_budget <= 0 or not text:
        return ""
    if estimate_text_tokens(text) <= token_budget:
        return text

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high) // 2
        if estimate_text_tokens(text[mid:]) <= token_budget:
            high = mid
        else:
            low = mid + 1
    return text[low:].lstrip()


def prepare_public_transcript(
    public_summary: str,
    public_events: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    events = [event for event in public_events if isinstance(event, dict)]
    if len(events) <= SUMMARY_EVENT_THRESHOLD:
        return str(public_summary or ""), events

    older = events[:-MAX_RECENT_EVENTS]
    recent = events[-MAX_RECENT_EVENTS:]
    existing_summary = str(public_summary or "").strip()
    # 增量归档：existing_summary 是上一轮本函数的产物，其中出现过的旧事件不再重渲染。
    # 此前每轮把「除最近 16 条外的全部事件」整体拼回去，同一事件逐轮翻倍复制；
    # 超预算后头部截断留下的恰是重复多遍的最旧事件，最新归档反而最先被切掉。
    fresh_lines = [
        line
        for line in (format_public_event(event) for event in older)
        if line not in existing_summary
    ]
    merged = existing_summary
    if fresh_lines:
        marker = "" if ARCHIVE_MARKER in existing_summary else f"{ARCHIVE_MARKER}\n"
        merged = "\n".join(part for part in [existing_summary, marker + "\n".join(fresh_lines)] if part)
    if estimate_text_tokens(merged) > SUMMARY_TOKEN_BUDGET:
        merged = _trim_head_to_token_budget(merged, SUMMARY_TOKEN_BUDGET)
    return merged, recent


def render_public_context(public_summary: str, recent_events: list[dict[str, Any]]) -> str:
    parts = []
    if public_summary.strip():
        parts.append("【公开庭审摘要】\n" + public_summary.strip())
    if recent_events:
        parts.append("【近期公开庭审记录】\n" + "\n".join(format_public_event(event) for event in recent_events))
    return "\n\n".join(parts).strip() or "暂无公开庭审记录。"


__all__ = ["format_public_event", "prepare_public_transcript", "render_public_context", "speaker_label"]
