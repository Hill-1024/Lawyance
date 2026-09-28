"""SQLAlchemy persistence. Production requires PostgreSQL; SQLite is test-only."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from fastapi import HTTPException


def now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "workbench_items"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    searchable: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (
        Index("ix_workbench_scope", "owner", "kind", "project_id", "updated_at"),
    )


class Version(Base):
    __tablename__ = "workbench_versions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(100), index=True)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("document_id", "revision"),)


class Event(Base):
    __tablename__ = "workbench_events"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("run_id", "seq"),)


class Receipt(Base):
    __tablename__ = "workbench_receipts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


def database_url():
    url = os.environ.get("LAWVER_DATABASE_URL", "")
    if not url:
        raise HTTPException(503, "云端工作台尚未配置数据库，原有资料仍可访问。")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+") and not (
        os.environ.get("LAWVER_WORKBENCH_TESTING") == "1" and url.startswith("sqlite")
    ):
        raise RuntimeError("Workbench requires PostgreSQL")
    return url


@lru_cache(maxsize=4)
def engine_for(url):
    return create_engine(
        url,
        pool_pre_ping=True,
        **(
            {"connect_args": {"check_same_thread": False}}
            if url.startswith("sqlite")
            else {}
        ),
    )


@contextmanager
def transaction():
    with sessionmaker(engine_for(database_url()), expire_on_commit=False)() as session:
        with session.begin():
            yield session


def get_item(session, owner, identifier, kind=None, *, deleted=False, lock=False):
    from sqlalchemy import select

    query = select(Item).where(Item.id == identifier, Item.owner == owner)
    if kind:
        query = query.where(Item.kind == kind)
    if not deleted:
        query = query.where(Item.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    item = session.scalar(query)
    if not item:
        raise HTTPException(404, "内容不存在或无权访问")
    if item.project_id and not deleted:
        project = session.get(Item, item.project_id)
        if not project or project.owner != owner or project.deleted_at:
            raise HTTPException(404, "所属项目不可访问")
    return item


def check_revision(item, expected):
    if expected != item.revision:
        raise HTTPException(
            409,
            {
                "message": "内容已在其他位置更新，请保留本地修改后对照最新版本。",
                "current": public(item),
            },
        )


def public(item):
    data = {
        k: v
        for k, v in item.data.items()
        if k not in {"encrypted_secret", "blob_key", "lease_until", "worker_id"}
    }
    if item.kind == "connector":
        data["has_secret"] = bool(item.data.get("encrypted_secret"))
    return dict(
        id=item.id,
        kind=item.kind,
        project_id=item.project_id,
        parent_id=item.parent_id,
        title=item.title,
        revision=item.revision,
        data=data,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
        deleted_at=item.deleted_at.isoformat() if item.deleted_at else None,
    )


class BlobStore:
    def __init__(self):
        self.root = Path(
            os.environ.get("LAWVER_BLOB_DIR")
            or Path(os.environ.get("LAWVER_DATA_DIR", "data")) / "workbench-blobs"
        )

    def put(self, content: bytes) -> str:
        import hashlib

        key = hashlib.sha256(content).hexdigest()
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not destination.exists():
            temporary = destination.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as out:
                    os.chmod(temporary, 0o600)
                    out.write(content)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return key

    def path(self, key):
        import re

        if not re.fullmatch(r"[a-f0-9]{64}", str(key)):
            raise HTTPException(400, "无效文件标识")
        return self.root / key[:2] / key
