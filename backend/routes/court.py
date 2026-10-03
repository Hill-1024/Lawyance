"""
模块描述：模拟法庭单回合流式 API 与角色记忆清理 API。
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from billing import ledger as billing, metering, pricing
from infra import account_store
from starlette.concurrency import run_in_threadpool

from schemas import CourtMemoryClearRequest, CourtTurnRequest
from services.auth_dependencies import get_current_user
from services.court_pipeline import (
    memory_conflict_detail,
    prepare_court_turn,
    role_memory_scope,
    role_scopes,
    run_court_turn_stream,
)
from services.memory_coordinator import MemoryRevisionConflict, call_memory_tool
from services.workspace_service import get_workspace_scope


router = APIRouter()
logger = logging.getLogger(__name__)


def _clear_memory_scopes(scopes: list[str]) -> list[str]:
    cleared: list[str] = []
    for scope in scopes:
        call_memory_tool("clear_conversation_memory", {}, scope)
        cleared.append(scope)
    return cleared


@router.post("/api/court/turn")
async def court_turn_endpoint(request: CourtTurnRequest, current_user: str = Depends(get_current_user)):
    # 读库一律进线程池：这是 async 端点，同步查库会卡住同一事件循环上的全部 SSE 流。
    allowed, refusal = await run_in_threadpool(billing.can_spend, current_user)
    if not allowed:
        raise HTTPException(status_code=402, detail=refusal)
    # 计费倍率在开轮时快照（与工作台 worker 同口径）；账号只读一次，不再为三个字段各查一遍。
    account = (await run_in_threadpool(account_store.get_user, current_user)) or {}
    multiplier = pricing.multiplier_for(
        account.get("plan", "metered"),
        account.get("billing_cycle", "prepaid"),
        account.get("credit_multiplier"),
    )
    try:
        prepared = await prepare_court_turn(request, current_user)
    except MemoryRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=memory_conflict_detail(exc))

    async def generate():
        turn = metering.begin_turn(
            current_user,
            multiplier=multiplier,
            ref_id=request.court_session_id,
            reason="庭审推演",
        )
        try:
            async for event in run_court_turn_stream(prepared):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Court turn stream failed")
            payload = {
                "type": "error",
                "code": "court_turn_failed",
                "content": "庭审处理失败，请稍后重试。",
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            # 庭审同样按轮结算：中断的轮次也已经消耗了模型调用。
            summary = await asyncio.to_thread(billing.settle, turn)
            metering.end_turn()
            if summary:
                yield f"data: {json.dumps({'type': 'usage', 'content': summary}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/court/memory/clear")
async def clear_court_memory(
    request: CourtMemoryClearRequest,
    current_user: str = Depends(get_current_user),
):
    """清除指定庭审下 AI 角色的私有记忆。撤回到任意点时由前端调用。"""
    base_scope = get_workspace_scope(current_user, request.court_session_id)
    requested_roles = request.roles
    if requested_roles:
        target_scopes = [
            role_memory_scope(base_scope, role)
            for role in requested_roles
            if role in {"judge", "opponent", "reviewer", "user"}
        ]
    else:
        target_scopes = list(role_scopes(base_scope).values())

    try:
        cleared = await run_in_threadpool(_clear_memory_scopes, target_scopes)
    except Exception:
        logger.exception("Failed to clear court memory")
        raise HTTPException(status_code=500, detail="庭审记忆清理失败，请稍后重试。")
    return {"status": "success", "cleared": cleared}
