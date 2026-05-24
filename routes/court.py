"""
模块描述：模拟法庭单回合流式 API 与角色记忆清理 API。
"""

import json
import traceback

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from memory_system import MemoryRevisionConflict
from schemas import CourtMemoryClearRequest, CourtTurnRequest
from services.auth_dependencies import get_current_user
from services.court_pipeline import (
    memory_conflict_detail,
    prepare_court_turn,
    role_memory_scope,
    role_scopes,
    run_court_turn_stream,
)
from services.memory_coordinator import call_memory_tool
from services.workspace_service import get_workspace_scope


router = APIRouter()


@router.post("/api/court/turn")
async def court_turn_endpoint(request: CourtTurnRequest, current_user: str = Depends(get_current_user)):
    try:
        prepared = await prepare_court_turn(request, current_user)
    except MemoryRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=memory_conflict_detail(exc))

    async def generate():
        try:
            async for event in run_court_turn_stream(prepared):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
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

    cleared = []
    for scope in target_scopes:
        call_memory_tool("clear_conversation_memory", {}, scope)
        cleared.append(scope)
    return {"status": "success", "cleared": cleared}
