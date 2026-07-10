"""
模块描述：聊天、标题摘要和记忆同步 API。
"""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from function_calling import call
from memory_system import MemoryRevisionConflict
from output_sanitizer import strip_think_blocks, strip_wrapper_tags
from schemas import ChatRequest, MemorySyncRequest, ResumeAckRequest, StreamCancelRequest, SummarizeRequest
from services.auth_dependencies import get_current_user
from services.chat_pipeline import CHAT_FAILURE_MESSAGE, prepare_chat_turn, run_agent_once, run_agent_stream
from services.memory_coordinator import memory_conflict_detail, sync_memory_cache
from services import stream_buffer
from services.workspace_service import get_workspace_scope


router = APIRouter()
logger = logging.getLogger(__name__)
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _direct_stream(prepared, buffered: bool = False, unavailable_reason: str | None = None):
    seq = 0
    yield _sse_event({
        "type": "stream_start",
        "seq": seq,
        "stream_id": prepared.turn_id,
        "buffered": buffered,
    })
    seq += 1
    if unavailable_reason:
        yield _sse_event({
            "type": "resume_unavailable",
            "seq": seq,
            "stream_id": prepared.turn_id,
            "reason": unavailable_reason,
        })
        seq += 1
    try:
        async for event in run_agent_stream(prepared):
            payload = dict(event)
            payload["seq"] = seq
            seq += 1
            yield _sse_event(payload)
    except Exception:
        logger.exception("Direct chat stream failed")
        yield _sse_event({
            "type": "error",
            "code": "chat_generation_failed",
            "seq": seq,
            "content": CHAT_FAILURE_MESSAGE,
        })
        seq += 1
    yield _sse_event({"type": "done", "seq": seq, "final_seq": seq})
    yield "data: [DONE]\n\n"


async def _buffered_stream(stream_id: str, from_seq: int):
    async for payload in stream_buffer.reader(stream_id, from_seq):
        yield _sse_event(payload)
    yield "data: [DONE]\n\n"


# 服务端 SSE 心跳：空闲间隙（如 OCP/长思考无 token 输出时）每隔 HEARTBEAT_INTERVAL 秒
# 发一条 SSE 注释行 ": ping"。注释行不是 data: 事件，前端与原生前台服务都会自然跳过，
# 不污染内容；但能让 TCP 持续有字节流动，使原生端的有限读超时只在连接真正死亡时触发。
HEARTBEAT_INTERVAL = 15.0
HEARTBEAT_COMMENT = ": ping\n\n"
# 单槽背压：下游暂停读取时，pump 最多只允许领先一个块，避免把完整上游响应
# 预先搬进进程内存。该值是安全上限，不通过环境变量开放“无限”配置。
HEARTBEAT_QUEUE_MAX_CHUNKS = 1


async def _with_heartbeat(source):
    # 用单一 pump 任务消费 source，使其内部 set/reset 的 ContextVar 始终落在同一个 Context；
    # 心跳循环只从队列取值并按超时插入 ": ping"。
    # 不可用 ensure_future(__anext__()) 逐次取值——那会让每个 __anext__ 运行在各自复制的 Context 中，
    # 导致 run_agent_stream 的 contextvar token “created in a different Context”。
    queue: asyncio.Queue = asyncio.Queue(maxsize=HEARTBEAT_QUEUE_MAX_CHUNKS)
    done_marker = object()
    error_box: list[Exception] = []

    async def _pump():
        cancelled = False
        try:
            async for chunk in source:
                await queue.put(chunk)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:  # 转发给消费侧统一抛出，保持原有异常语义
            error_box.append(exc)
        finally:
            # 消费侧取消时不再需要终止标记；若队列已满还阻塞写标记，
            # aclose() 会与 pump 互相等待。
            if not cancelled:
                await queue.put(done_marker)

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                yield HEARTBEAT_COMMENT
                continue
            if item is done_marker:
                break
            yield item
        if error_box:
            raise error_box[0]
    finally:
        if not pump_task.done():
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass


def _fallback_conversation_title(history: list[dict]) -> str:
    import re

    for msg in history:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "")
        content = re.sub(r"\[用户已上传以下文件.*?\]", "", content, flags=re.DOTALL)
        content = re.sub(r"</?(final_answer|think|response)[^>]*>", "", content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"\s+", " ", content).strip().strip('"').strip("'")
        if content:
            return content[:20] + ("..." if len(content) > 20 else "")
    return "New Chat"


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    try:
        prepared = await prepare_chat_turn(request, current_user)
    except MemoryRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=memory_conflict_detail(exc))

    if request.stream:
        if request.resume_enabled:
            state = await stream_buffer.create(prepared.turn_id, current_user)
            if state is None:
                return StreamingResponse(
                    _with_heartbeat(_direct_stream(prepared, buffered=False, unavailable_reason="quota")),
                    media_type="text/event-stream",
                    headers=SSE_HEADERS,
                )

            await stream_buffer.append(prepared.turn_id, {
                "type": "stream_start",
                "stream_id": prepared.turn_id,
                "buffered": True,
            })
            task = asyncio.create_task(stream_buffer.produce(prepared.turn_id, prepared))
            await stream_buffer.set_task(prepared.turn_id, task)

            return StreamingResponse(
                _with_heartbeat(_buffered_stream(prepared.turn_id, from_seq=-1)),
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )

        return StreamingResponse(
            _with_heartbeat(_direct_stream(prepared, buffered=False)),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    try:
        return await run_agent_once(prepared)
    except Exception:
        logger.exception("Non-stream chat request failed")
        raise HTTPException(status_code=500, detail=CHAT_FAILURE_MESSAGE)


@router.get("/api/chat/resume/{stream_id}")
async def resume_chat_stream(
    stream_id: Annotated[str, Path(min_length=1, max_length=128)],
    from_seq: Annotated[int, Query(ge=-1, le=2**63 - 1)] = -1,
    current_user: str = Depends(get_current_user),
):
    state = await stream_buffer.get(stream_id, current_user)
    if state is None:
        raise HTTPException(status_code=410, detail={"error": "stream_expired"})
    return StreamingResponse(
        _with_heartbeat(_buffered_stream(stream_id, from_seq)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/api/chat/ack")
async def ack_chat_stream(request: ResumeAckRequest, current_user: str = Depends(get_current_user)):
    trimmed_to = await stream_buffer.ack(request.stream_id, current_user, request.acked_seq)
    if trimmed_to is None:
        raise HTTPException(status_code=404, detail="stream_not_found")
    return {"ok": True, "trimmed_to": trimmed_to}


@router.post("/api/chat/cancel")
async def cancel_chat_stream(request: StreamCancelRequest, current_user: str = Depends(get_current_user)):
    cancelled = await stream_buffer.cancel(request.stream_id, current_user)
    if not cancelled:
        raise HTTPException(status_code=404, detail="stream_not_found")
    return {"ok": True}


@router.post("/api/summarize")
async def summarize_endpoint(request: SummarizeRequest, current_user: str = Depends(get_current_user)):
    history = request.history
    if not history or len(history) == 0:
        return {"title": "New Chat"}
    fallback_title = _fallback_conversation_title(history)
    temp_mem = [{"role": "system", "content": "你是一个对话标题生成器。只输出简短标题文本，不要包含标点符号、引号或任何 XML 标签。"}]
    temp_mem.append({
        "role": "user",
        "content": "请用一句话（不超过10个字）总结以下对话内容作为标题。只输出标题文本。\n\n"
        + "\n".join([f"{m.get('role','')}: {(m.get('content','') or '')[:100]}" for m in history[:6]]),
    })
    try:
        response = await call(temp_mem, stream=False, include_tools=False)
        content = response.content or ""
        content = strip_think_blocks(content)
        content = strip_wrapper_tags(content)
        title = content.strip().strip('"').strip("'")
        return {"title": title or fallback_title}
    except Exception as e:
        print(f"[标题摘要] 生成失败，使用兜底标题: {e}")
        return {"title": fallback_title}


@router.post("/api/memory/sync")
async def sync_memory_endpoint(request: MemorySyncRequest, current_user: str = Depends(get_current_user)):
    workspace_scope = get_workspace_scope(current_user, request.conversation_id)
    from services.conversation_state import active_conversations
    import time

    active_conversations[workspace_scope] = time.time()
    try:
        return await run_in_threadpool(
            sync_memory_cache,
            workspace_scope,
            request.memory_snapshot,
            request.history,
            request.mode,
            request.expected_revision,
            request.memory_conflict_strategy,
        )
    except MemoryRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=memory_conflict_detail(exc))
