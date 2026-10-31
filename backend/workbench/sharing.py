"""Authenticated URL-share management and anonymous, revocable snapshot reads."""

import copy
from datetime import timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from workbench.api import gate, receipt
from workbench.conversation_export import formal_messages
from workbench.store import ConversationShare, Item, get_item, new_id, now, transaction

router = APIRouter(tags=["conversation-sharing"])
PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Referrer-Policy": "no-referrer",
}


class CreateShare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: Literal[7, 14, 21, 30] = 30


def _utc(value):
    # PostgreSQL retains timezone information; SQLite returns naive UTC values.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _state(share):
    if share.revoked_at:
        return "revoked"
    return "expired" if _utc(share.expires_at) <= now() else "active"


def _describe(share):
    if share is None:
        return {"status": "not_created"}
    status = _state(share)
    return {
        "status": status,
        "token": share.token,
        "path": f"/share/{share.token}" if status == "active" else None,
        "created_at": _utc(share.created_at).isoformat(),
        "expires_at": _utc(share.expires_at).isoformat(),
    }


@router.get("/api/workbench/conversations/{identifier}/share")
def share_status(identifier: str, user=Depends(gate)):
    with transaction() as session:
        get_item(session, user, identifier, "conversation")
        return JSONResponse(_describe(session.get(ConversationShare, identifier)), headers=PRIVATE_HEADERS)


@router.post("/api/workbench/conversations/{identifier}/share")
def create_share(identifier: str, body: CreateShare, idempotency_key: str | None = Header(None), user=Depends(gate)):
    try:
        with transaction() as session:
            conversation = get_item(session, user, identifier, "conversation", lock=True)
            if conversation.project_id:
                get_item(session, user, conversation.project_id, "project", lock=True)

            def create():
                share = session.get(ConversationShare, identifier)
                if share and _state(share) == "active":
                    return {"token": share.token}
                runs = session.scalars(select(Item).where(
                    Item.owner == user, Item.kind == "run", Item.parent_id == identifier,
                    Item.deleted_at.is_(None),
                ))
                if any(run.data.get("status") in ("queued", "running", "waiting_confirmation", "waiting_user") for run in runs):
                    raise HTTPException(409, "会话正在运行任务，请等待完成后再分享")
                messages = formal_messages(conversation.data.get("messages"))
                if not messages:
                    raise HTTPException(422, "会话还没有可分享的消息")
                if share is None:
                    share = ConversationShare(conversation_id=identifier, owner=user)
                    session.add(share)
                share.token = new_id()
                share.created_at = now()
                share.expires_at = share.created_at + timedelta(days=body.days)
                share.revoked_at = None
                share.snapshot = {"title": conversation.title, "messages": copy.deepcopy(messages)}
                session.flush()
                return {"token": share.token}

            saved = receipt(session, user, idempotency_key,
                            {"action": "create_conversation_share", "id": identifier, **body.model_dump()}, create)
            share = session.get(ConversationShare, identifier)
            # Retrying an old request must never resurrect a revoked share or mint a new token.
            if share is None or share.token != saved["token"] or _state(share) != "active":
                raise HTTPException(409, "该创建请求已失效，请刷新分享状态后重新创建")
            return JSONResponse(_describe(share), headers=PRIVATE_HEADERS)
    except IntegrityError:
        # Unique conversation_id/token also protects concurrent first creations in SQLite.
        raise HTTPException(409, "分享状态已变化，请刷新后重试") from None


@router.delete("/api/workbench/conversations/{identifier}/share/{token}")
def revoke_share(identifier: str, token: UUID, user=Depends(gate)):
    with transaction() as session:
        get_item(session, user, identifier, "conversation", lock=True)
        share = session.get(ConversationShare, identifier)
        if share is None or share.token != str(token):
            raise HTTPException(409, "分享状态已变化，请刷新后重试")
        share.revoked_at = share.revoked_at or now()
        share.snapshot = {}
        return JSONResponse(_describe(share), headers=PRIVATE_HEADERS)


def _limit_public(request: Request):
    from services.app_security import client_ip_for_request
    from services.rate_limit import hit

    result = hit("conversation-share", client_ip_for_request(request), limit=90, window_seconds=60)
    if not result.allowed:
        raise HTTPException(429, "访问过于频繁，请稍后重试",
                            headers={**PRIVATE_HEADERS, "Retry-After": str(result.retry_after)})


def _public_share(session, token):
    share = session.scalar(select(ConversationShare).where(ConversationShare.token == str(token)))
    if share is None or _state(share) != "active":
        raise HTTPException(404, "分享已过期或已撤回", headers=PRIVATE_HEADERS)
    try:
        get_item(session, share.owner, share.conversation_id, "conversation")
    except HTTPException:
        raise HTTPException(404, "分享已不可用", headers=PRIVATE_HEADERS) from None
    return share


@router.get("/api/shares/{token}", dependencies=[Depends(_limit_public)])
def read_share(token: UUID):
    with transaction() as session:
        share = _public_share(session, token)
        return JSONResponse({**share.snapshot, "expires_at": _utc(share.expires_at).isoformat()}, headers=PRIVATE_HEADERS)


@router.get("/api/shares/{token}/status", dependencies=[Depends(_limit_public)])
def public_status(token: UUID):
    with transaction() as session:
        share = _public_share(session, token)
        return JSONResponse({"expires_at": _utc(share.expires_at).isoformat()}, headers=PRIVATE_HEADERS)


def purge_expired_shares():
    """Discard expired content; retain small metadata for the owner's status indicator."""
    with transaction() as session:
        session.execute(update(ConversationShare).where(
            or_(ConversationShare.expires_at <= now(), ConversationShare.revoked_at.is_not(None)),
        ).values(snapshot={}))
