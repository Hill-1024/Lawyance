"""
模块描述：聊天、标题摘要和记忆同步 API。
"""

import json
import traceback

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from function_calling import call
from memory_system import MemoryRevisionConflict
from output_sanitizer import strip_think_blocks, strip_wrapper_tags
from schemas import ChatRequest, MemorySyncRequest, SummarizeRequest
from services.auth_dependencies import get_current_user
from services.chat_pipeline import prepare_chat_turn, run_agent_once, run_agent_stream
from services.memory_coordinator import memory_conflict_detail, sync_memory_cache
from services.workspace_service import get_workspace_scope


router = APIRouter()


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
        async def generate_agent():
            try:
                async for event in run_agent_stream(prepared):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as e:
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_agent(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        return await run_agent_once(prepared)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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
        return sync_memory_cache(
            workspace_scope,
            request.memory_snapshot,
            request.history,
            request.mode,
            request.expected_revision,
            request.memory_conflict_strategy,
        )
    except MemoryRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=memory_conflict_detail(exc))
