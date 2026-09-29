"""
模块描述：开屏公告——登录账号读取与自己相关的公告，sudo/admin 在控制台维护公告。

下发口径：公告 `active` 为真、当前时间落在 starts_at / ends_at 之间，且
`audience`（套餐 id 列表）为空或包含该账号的套餐。列表量级很小，直接取回后
在内存里过滤，避免依赖 JSON 包含运算符在各数据库上的方言差异。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from auth import get_user_record
from billing.models import Announcement
from infra.account_store import VALID_PLANS
from infra.database import transaction
from services.auth_dependencies import get_current_user, require_staff


router = APIRouter()

LEVELS = ("info", "warning", "danger")
_TITLE_MAX = 200
_BODY_MAX = 5_000
_ID_PATTERN = r"^[A-Za-z0-9_-]{1,100}$"


def ensure_table() -> None:
    """建表（缺才建）。生产走 alembic，这里保证冷启动与测试不会因为少表而 500。"""
    from infra.database import database_url, engine_for

    engine = engine_for(database_url())
    Announcement.__table__.create(engine, checkfirst=True)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite 取回的 DateTime 可能不带时区；统一按 UTC 解释再比较。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _validate_scope(
    *,
    title: str,
    level: str,
    audience: list[str],
    starts_at: Optional[datetime],
    ends_at: Optional[datetime],
) -> None:
    if not title.strip():
        raise HTTPException(422, "公告标题不能为空")
    if level not in LEVELS:
        raise HTTPException(422, "级别只能是 info、warning 或 danger")
    unknown = [plan for plan in audience if plan not in VALID_PLANS]
    if unknown:
        raise HTTPException(422, f"受众包含未知套餐：{'、'.join(unknown)}")
    if starts_at is not None and ends_at is not None and _aware(ends_at) <= _aware(starts_at):
        raise HTTPException(422, "结束时间必须晚于开始时间")


def _clean_audience(audience: list[str]) -> list[str]:
    """去重并保持顺序；`全部` 用空列表表达。"""
    seen: list[str] = []
    for plan in audience:
        if plan not in seen:
            seen.append(plan)
    return seen


def _iso(value: Optional[datetime]) -> Optional[str]:
    aware = _aware(value)
    return aware.isoformat() if aware else None


def _to_dict(row: Announcement) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body or "",
        "level": row.level,
        "audience": list(row.audience or []),
        "starts_at": _iso(row.starts_at),
        "ends_at": _iso(row.ends_at),
        "active": bool(row.active),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


def _is_visible(row: Announcement, plan: str, now: datetime) -> bool:
    if not row.active:
        return False
    starts_at = _aware(row.starts_at)
    ends_at = _aware(row.ends_at)
    if starts_at is not None and starts_at > now:
        return False
    if ends_at is not None and ends_at < now:
        return False
    audience = list(row.audience or [])
    return not audience or plan in audience


# ─── 用户侧：只读下发 ──────────────────────────────────────────────────────


@router.get("/api/announcements")
def my_announcements(user: str = Depends(get_current_user)):
    """当前账号可见的开屏公告，最新在前；前端只展示未读的第一条。"""
    ensure_table()
    record = get_user_record(user) or {}
    plan = record.get("plan") or "metered"
    now = datetime.now(timezone.utc)
    with transaction() as session:
        rows = session.scalars(
            select(Announcement).order_by(Announcement.created_at.desc())
        ).all()
        visible = [row for row in rows if _is_visible(row, plan, now)]
    return {
        "status": "success",
        "announcements": [
            {
                "id": row.id,
                "title": row.title,
                "body": row.body or "",
                "level": row.level,
                "starts_at": _iso(row.starts_at),
                "ends_at": _iso(row.ends_at),
            }
            for row in visible
        ],
    }


# ─── 管理侧：完整 CRUD ─────────────────────────────────────────────────────


class AnnouncementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=_TITLE_MAX)
    body: str = Field(default="", max_length=_BODY_MAX)
    level: str = Field(default="info", max_length=16)
    audience: list[str] = Field(default_factory=list, max_length=len(VALID_PLANS))
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    active: bool = True

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("公告标题不能为空")
        return value


class AnnouncementPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=_TITLE_MAX)
    body: Optional[str] = Field(default=None, max_length=_BODY_MAX)
    level: Optional[str] = Field(default=None, max_length=16)
    audience: Optional[list[str]] = Field(default=None, max_length=len(VALID_PLANS))
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    active: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("公告标题不能为空")
        return value


@router.get("/api/admin/announcements")
def admin_announcements(actor: str = Depends(require_staff)):
    """全部公告（含未启用与已过期），最新在前。"""
    ensure_table()
    with transaction() as session:
        rows = session.scalars(
            select(Announcement).order_by(Announcement.created_at.desc())
        ).all()
        return {"status": "success", "announcements": [_to_dict(row) for row in rows]}


@router.post("/api/admin/announcements")
def create_announcement(payload: AnnouncementCreate, actor: str = Depends(require_staff)):
    ensure_table()
    audience = _clean_audience(payload.audience)
    _validate_scope(
        title=payload.title,
        level=payload.level,
        audience=audience,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    with transaction() as session:
        row = Announcement(
            title=payload.title.strip(),
            body=payload.body,
            level=payload.level,
            audience=audience,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            active=payload.active,
            created_by=actor,
        )
        session.add(row)
        session.flush()
        result = _to_dict(row)
    return {"status": "success", "announcement": result}


@router.patch("/api/admin/announcements/{announcement_id}")
def update_announcement(
    payload: AnnouncementPatch,
    announcement_id: str = Path(min_length=1, max_length=100, pattern=_ID_PATTERN),
    actor: str = Depends(require_staff),
):
    ensure_table()
    fields = payload.model_dump(exclude_unset=True)
    with transaction() as session:
        row = session.get(Announcement, announcement_id)
        if row is None:
            raise HTTPException(404, "公告不存在")

        title = fields["title"] if fields.get("title") is not None else row.title
        body = fields["body"] if fields.get("body") is not None else row.body
        level = fields["level"] if fields.get("level") is not None else row.level
        audience = (
            _clean_audience(fields["audience"])
            if fields.get("audience") is not None
            else list(row.audience or [])
        )
        # starts_at / ends_at 显式传 null 表示清除边界。
        starts_at = fields["starts_at"] if "starts_at" in fields else row.starts_at
        ends_at = fields["ends_at"] if "ends_at" in fields else row.ends_at
        active = fields["active"] if fields.get("active") is not None else row.active

        _validate_scope(
            title=title,
            level=level,
            audience=audience,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        row.title = title.strip()
        row.body = body
        row.level = level
        row.audience = audience
        row.starts_at = starts_at
        row.ends_at = ends_at
        row.active = active
        session.flush()
        result = _to_dict(row)
    return {"status": "success", "announcement": result}


@router.delete("/api/admin/announcements/{announcement_id}")
def delete_announcement(
    announcement_id: str = Path(min_length=1, max_length=100, pattern=_ID_PATTERN),
    actor: str = Depends(require_staff),
):
    ensure_table()
    with transaction() as session:
        row = session.get(Announcement, announcement_id)
        if row is None:
            raise HTTPException(404, "公告不存在")
        session.delete(row)
    return {"status": "success", "message": "公告已删除"}
