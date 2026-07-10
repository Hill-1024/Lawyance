"""
模块描述：聊天流式续传的进程内缓冲区，负责短期保留已授权的 SSE 事件。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Optional

from services.chat_pipeline import PreparedChatTurn, run_agent_stream


logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), 0)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %s", name, raw, default)
        return default


HARD_MAX_STREAMS_PER_USER = 32
HARD_MAX_BYTES_PER_STREAM = 8 * 1024 * 1024
HARD_MAX_BYTES_GLOBAL = 512 * 1024 * 1024
HARD_MAX_TTL_SECONDS = 24 * 60 * 60
HARD_MAX_READERS_PER_STREAM = 16
HARD_MAX_READER_QUEUE_EVENTS = 256
HARD_MAX_READER_QUEUE_BYTES = 4 * 1024 * 1024
HARD_MAX_EVENTS_PER_STREAM = 8192
MAX_STREAMS_PER_USER = min(
    max(_env_int("LAWVER_RESUME_MAX_STREAMS_PER_USER", 3), 1),
    HARD_MAX_STREAMS_PER_USER,
)
MAX_BYTES_PER_STREAM = min(
    max(_env_int("LAWVER_RESUME_MAX_BYTES_PER_STREAM", 2 * 1024 * 1024), 64 * 1024),
    HARD_MAX_BYTES_PER_STREAM,
)
MAX_BYTES_GLOBAL = min(
    max(_env_int("LAWVER_RESUME_MAX_BYTES_GLOBAL", 128 * 1024 * 1024), 1024 * 1024),
    HARD_MAX_BYTES_GLOBAL,
)
TTL_SECONDS = min(
    max(_env_int("LAWVER_RESUME_TTL_SECONDS", 45 * 60), 60),
    HARD_MAX_TTL_SECONDS,
)
SWEEP_SECONDS = min(max(_env_int("LAWVER_RESUME_SWEEP_SECONDS", 60), 1), 60 * 60)
MAX_READERS_PER_STREAM = min(
    max(_env_int("LAWVER_RESUME_MAX_READERS_PER_STREAM", 4), 1),
    HARD_MAX_READERS_PER_STREAM,
)
MAX_READER_QUEUE_EVENTS = min(
    max(_env_int("LAWVER_RESUME_MAX_READER_QUEUE_EVENTS", 64), 1),
    HARD_MAX_READER_QUEUE_EVENTS,
)
MAX_READER_QUEUE_BYTES = min(
    max(_env_int("LAWVER_RESUME_MAX_READER_QUEUE_BYTES", 1024 * 1024), 64 * 1024),
    HARD_MAX_READER_QUEUE_BYTES,
)
MAX_EVENTS_PER_STREAM = min(
    max(_env_int("LAWVER_RESUME_MAX_EVENTS_PER_STREAM", 2048), 1),
    HARD_MAX_EVENTS_PER_STREAM,
)


@dataclass
class ReaderState:
    # 额外预留一个终止槽，保证 finish/delete 不会因数据槽已满而 QueueFull。
    queue: asyncio.Queue[Optional[dict[str, Any]]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_READER_QUEUE_EVENTS + 1)
    )
    closed: bool = False
    byte_count: int = 0


@dataclass
class StreamState:
    stream_id: str
    user: str
    events: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    next_seq: int = 0
    done: bool = False
    error: Optional[str] = None
    final_seq: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    last_acked_seq: int = -1
    byte_count: int = 0
    task: Optional[asyncio.Task] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    readers: dict[int, ReaderState] = field(default_factory=dict)
    truncated: bool = False
    truncated_at_seq: Optional[int] = None


_REGISTRY: dict[str, StreamState] = {}
_USER_STREAMS: dict[str, set[str]] = {}
_GLOBAL_BYTES = 0
_GLOBAL_LOCK = asyncio.Lock()
_SWEEP_TASK: Optional[asyncio.Task] = None
_READER_ID = 0


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _user_stream_count(user: str) -> int:
    return len(_USER_STREAMS.get(user, set()))


def _drain_reader_queue(reader: ReaderState) -> None:
    while True:
        try:
            reader.queue.get_nowait()
        except asyncio.QueueEmpty:
            reader.byte_count = 0
            return


def _close_reader(reader: ReaderState) -> None:
    if reader.closed:
        return
    reader.closed = True
    try:
        reader.queue.put_nowait(None)
    except asyncio.QueueFull:
        # 正常情况下终止槽始终保留；这里仍采用 fail-closed 清空，确保清理路径
        # 永不因 QueueFull 泄漏状态或打断 sweep/shutdown。
        _drain_reader_queue(reader)
        reader.queue.put_nowait(None)


def _disconnect_slow_reader(
    state: StreamState,
    reader_id: int,
    reader: ReaderState,
    event_seq: int,
) -> None:
    reader.closed = True
    _drain_reader_queue(reader)
    unavailable = {
        "type": "resume_unavailable",
        "seq": max(event_seq, 0),
        "reason": "slow_reader",
        "stream_id": state.stream_id,
    }
    reader.queue.put_nowait(unavailable)
    reader.byte_count = _payload_size(unavailable)
    state.readers.pop(reader_id, None)


def _remove_state(stream_id: str) -> Optional[StreamState]:
    global _GLOBAL_BYTES
    state = _REGISTRY.pop(stream_id, None)
    if state is None:
        return None
    streams = _USER_STREAMS.get(state.user)
    if streams is not None:
        streams.discard(stream_id)
        if not streams:
            _USER_STREAMS.pop(state.user, None)
    _GLOBAL_BYTES = max(0, _GLOBAL_BYTES - state.byte_count)
    state.byte_count = 0
    for reader in list(state.readers.values()):
        _close_reader(reader)
    state.readers.clear()
    return state


def _evict_done_until_under_limit(required_bytes: int = 0) -> None:
    if _GLOBAL_BYTES + required_bytes <= MAX_BYTES_GLOBAL:
        return
    candidates = sorted(
        (state for state in _REGISTRY.values() if state.done),
        key=lambda state: state.created_at,
    )
    for state in candidates:
        removed = _remove_state(state.stream_id)
        if removed and _GLOBAL_BYTES + required_bytes <= MAX_BYTES_GLOBAL:
            return


async def create(stream_id: str, user: str) -> Optional[StreamState]:
    async with _GLOBAL_LOCK:
        _evict_done_until_under_limit()
        if MAX_STREAMS_PER_USER and _user_stream_count(user) >= MAX_STREAMS_PER_USER:
            return None
        if MAX_BYTES_GLOBAL and _GLOBAL_BYTES >= MAX_BYTES_GLOBAL:
            return None
        state = StreamState(stream_id=stream_id, user=user)
        _REGISTRY[stream_id] = state
        _USER_STREAMS.setdefault(user, set()).add(stream_id)
        return state


async def set_task(stream_id: str, task: asyncio.Task) -> None:
    async with _GLOBAL_LOCK:
        state = _REGISTRY.get(stream_id)
        if state is not None:
            state.task = task


async def append(stream_id: str, payload: dict[str, Any]) -> int:
    global _GLOBAL_BYTES
    state = _REGISTRY.get(stream_id)
    if state is None:
        return -1

    async with state.lock:
        seq = state.next_seq
        state.next_seq += 1
        event = dict(payload)
        event["seq"] = seq
        if event.get("type") == "done":
            event["final_seq"] = seq
            state.final_seq = seq

        size = _payload_size(event)
        should_store = not state.truncated
        if should_store and len(state.events) >= MAX_EVENTS_PER_STREAM:
            should_store = False
            state.truncated = True
            state.truncated_at_seq = seq
        if MAX_BYTES_PER_STREAM and state.byte_count + size > MAX_BYTES_PER_STREAM:
            should_store = False
            state.truncated = True
            state.truncated_at_seq = seq

        async with _GLOBAL_LOCK:
            if should_store and MAX_BYTES_GLOBAL:
                _evict_done_until_under_limit(size)
                if _GLOBAL_BYTES + size > MAX_BYTES_GLOBAL:
                    should_store = False
                    state.truncated = True
                    state.truncated_at_seq = seq
            if should_store:
                state.events.append((seq, event))
                state.byte_count += size
                _GLOBAL_BYTES += size

        for reader_id, reader in list(state.readers.items()):
            if reader.closed:
                continue
            if (
                reader.queue.qsize() >= MAX_READER_QUEUE_EVENTS
                or reader.byte_count + size > MAX_READER_QUEUE_BYTES
            ):
                _disconnect_slow_reader(state, reader_id, reader, seq)
                continue
            try:
                reader.queue.put_nowait(event)
                reader.byte_count += size
            except asyncio.QueueFull:
                _disconnect_slow_reader(state, reader_id, reader, seq)
        return seq


async def finish(stream_id: str, error: Optional[str] = None) -> None:
    state = _REGISTRY.get(stream_id)
    if state is None:
        return
    async with state.lock:
        state.done = True
        state.error = error
        if state.final_seq is None:
            state.final_seq = max(state.next_seq - 1, -1)
        for reader in list(state.readers.values()):
            _close_reader(reader)


async def get(stream_id: str, user: str) -> Optional[StreamState]:
    state = _REGISTRY.get(stream_id)
    if state is None or state.user != user:
        return None
    return state


async def reader(stream_id: str, from_seq: int) -> AsyncIterator[dict[str, Any]]:
    global _READER_ID
    state = _REGISTRY.get(stream_id)
    if state is None:
        return

    reader_state = ReaderState()
    reader_id: Optional[int] = None
    async with state.lock:
        truncated_upper_bound = state.final_seq if state.final_seq is not None else state.next_seq - 1
        if state.truncated and from_seq < truncated_upper_bound:
            unavailable = {
                "type": "resume_unavailable",
                "seq": max(from_seq + 1, 0),
                "reason": "quota",
                "stream_id": stream_id,
            }
            replay: list[dict[str, Any]] = [unavailable]
            is_done = True
        elif len(state.readers) >= MAX_READERS_PER_STREAM:
            replay = [{
                "type": "resume_unavailable",
                "seq": max(from_seq + 1, 0),
                "reason": "reader_limit",
                "stream_id": stream_id,
            }]
            is_done = True
        else:
            replay = [dict(payload) for seq, payload in state.events if seq > from_seq]
            is_done = state.done

        if not is_done:
            _READER_ID += 1
            reader_id = _READER_ID
            state.readers[reader_id] = reader_state

    for payload in replay:
        seq = int(payload.get("seq", -1))
        if seq > from_seq:
            from_seq = seq
            yield payload

    if is_done:
        return

    try:
        while True:
            event = await reader_state.queue.get()
            if event is None:
                break
            reader_state.byte_count = max(0, reader_state.byte_count - _payload_size(event))
            if int(event.get("seq", -1)) > from_seq:
                from_seq = int(event["seq"])
                yield dict(event)
            if event.get("type") == "resume_unavailable" and event.get("reason") == "slow_reader":
                break
    finally:
        if reader_id is not None:
            async with state.lock:
                state.readers.pop(reader_id, None)


async def ack(stream_id: str, user: str, acked_seq: int) -> Optional[int]:
    global _GLOBAL_BYTES
    state = await get(stream_id, user)
    if state is None:
        return None

    async with state.lock:
        state.last_acked_seq = max(state.last_acked_seq, acked_seq)
        kept: list[tuple[int, dict[str, Any]]] = []
        removed_bytes = 0
        for seq, payload in state.events:
            if seq <= acked_seq:
                removed_bytes += _payload_size(payload)
            else:
                kept.append((seq, payload))
        state.events = kept
        state.byte_count = max(0, state.byte_count - removed_bytes)
        async with _GLOBAL_LOCK:
            _GLOBAL_BYTES = max(0, _GLOBAL_BYTES - removed_bytes)

        final_seq = state.final_seq
        should_delete = state.done and final_seq is not None and acked_seq >= final_seq

    if should_delete:
        await delete(stream_id)
    return acked_seq


async def cancel(stream_id: str, user: str) -> bool:
    state = await get(stream_id, user)
    if state is None:
        return False
    task = state.task
    if task and not task.done():
        task.cancel()
    await delete(stream_id)
    return True


async def delete(stream_id: str) -> None:
    async with _GLOBAL_LOCK:
        state = _remove_state(stream_id)
    if state is None:
        return
    task = state.task
    if task and not task.done():
        task.cancel()


async def produce(stream_id: str, prepared: PreparedChatTurn) -> None:
    try:
        async for event in run_agent_stream(prepared):
            await append(stream_id, event)
        await append(stream_id, {"type": "done"})
        await finish(stream_id)
    except asyncio.CancelledError:
        await finish(stream_id, error="cancelled")
        raise
    except Exception:
        logger.exception("Buffered chat stream failed for %s", stream_id)
        await append(stream_id, {
            "type": "error",
            "code": "chat_generation_failed",
            "content": "聊天处理失败，请稍后重试。",
        })
        await append(stream_id, {"type": "done"})
        await finish(stream_id, error="chat_generation_failed")


async def sweep_once(now: Optional[float] = None) -> int:
    now = now if now is not None else time.time()
    expired = [
        stream_id
        for stream_id, state in list(_REGISTRY.items())
        if TTL_SECONDS and now - state.created_at > TTL_SECONDS
    ]
    for stream_id in expired:
        await delete(stream_id)
    return len(expired)


async def _sweep_loop() -> None:
    try:
        while True:
            await asyncio.sleep(max(SWEEP_SECONDS, 1))
            await sweep_once()
    except asyncio.CancelledError:
        raise


def enforce_single_worker() -> None:
    workers = _env_int("UVICORN_WORKERS", 1) or 1
    if workers <= 1:
        return
    message = (
        "LAWVER resume streaming uses in-process memory and is unreliable with "
        f"UVICORN_WORKERS={workers}; use one worker or shared storage."
    )
    if os.getenv("LAWVER_RESUME_REQUIRE_SINGLE_WORKER", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError(message)
    logger.warning(message)


def start(app: Any) -> None:
    global _SWEEP_TASK
    enforce_single_worker()
    if _SWEEP_TASK is None or _SWEEP_TASK.done():
        _SWEEP_TASK = asyncio.create_task(_sweep_loop())
    app.state.stream_buffer_sweep_task = _SWEEP_TASK


async def stop(app: Any) -> None:
    global _SWEEP_TASK
    task = getattr(app.state, "stream_buffer_sweep_task", None) or _SWEEP_TASK
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _SWEEP_TASK = None

    for stream_id in list(_REGISTRY):
        await delete(stream_id)


def stats() -> dict[str, Any]:
    return {
        "streams": len(_REGISTRY),
        "global_bytes": _GLOBAL_BYTES,
        "users": {user: len(streams) for user, streams in _USER_STREAMS.items()},
    }


__all__ = [
    "StreamState",
    "ack",
    "append",
    "cancel",
    "create",
    "delete",
    "get",
    "produce",
    "reader",
    "set_task",
    "start",
    "stats",
    "stop",
    "sweep_once",
]
