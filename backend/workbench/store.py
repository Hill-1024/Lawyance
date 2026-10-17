"""工作台内容的 SQLAlchemy 模型；引擎与事务来自 infra.database（账号同库）。"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from fastapi import HTTPException

from infra import database as shared
from infra.database import Base, engine_for, new_id, now

__all__ = [
    "Base",
    "Item",
    "Version",
    "Event",
    "Receipt",
    "BlobStore",
    "database_url",
    "engine_for",
    "get_item",
    "check_revision",
    "new_id",
    "now",
    "public",
    "transaction",
]


WORKBENCH_DB_MESSAGE = "云端工作台尚未配置数据库，原有资料仍可访问。"


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
    # 归档是独立于删除的可见性状态：非空表示已归档，值保留归档时间。
    # 旧版本把它写在 data["archived"] 里，迁移负责回填；读写都走这一列。
    archived_at: Mapped[datetime | None] = mapped_column(
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
    return shared.database_url(WORKBENCH_DB_MESSAGE)


_READY_URL: str | None = None


def ensure_tables() -> None:
    """建表（缺才建）。生产走 alembic；这里是自愈，避免「忘了迁移」变成满屏 500。

    checkfirst=True 且 alembic 首个 revision 用的也是 create_all，两条路径结果一致。
    同一连接串在本进程只检查一次。
    """
    global _READY_URL
    url = database_url()
    if _READY_URL == url:
        return
    # 走共享的串行建表入口：这里建的是全部表，正好与账号引导等线程里的单表建表撞车。
    engine = engine_for(url)
    shared.create_tables(engine, metadata=Base.metadata)
    # create_all 不会给已存在的表补列：新增列在这里做一次，旧库才不会在 SELECT 时炸。
    with engine.begin() as connection:
        columns = {c["name"] for c in inspect(connection).get_columns("workbench_items")}
        if "archived_at" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE workbench_items ADD COLUMN archived_at "
                    + ("DATETIME" if connection.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE")
                )
            )
            # 旧版本把归档标记放在 data JSON 里；新列建好后按 updated_at 回填一次。
            for identifier, data in connection.execute(
                text("SELECT id, data FROM workbench_items WHERE archived_at IS NULL")
            ):
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except ValueError:
                        continue
                if isinstance(data, dict) and data.get("archived"):
                    connection.execute(
                        text(
                            "UPDATE workbench_items SET archived_at = updated_at "
                            "WHERE id = :identifier"
                        ),
                        {"identifier": identifier},
                    )
    _READY_URL = url


class _Transaction:
    """先确保表存在，再开事务——顺带把「库还没迁移」变成一个可自愈的前置步骤。"""

    def __init__(self, message: str):
        self._message = message

    def __enter__(self):
        ensure_tables()
        self._inner = shared.transaction(self._message)
        return self._inner.__enter__()

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)


def transaction():
    return _Transaction(WORKBENCH_DB_MESSAGE)


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
    # 归档状态以列为准（旧数据里可能残留 data["archived"]，一律覆盖成当前值），
    # 同时保留 data.archived 这个历史字段，避免旧版客户端读到相反的状态。
    data.pop("archived", None)
    data["archived"] = item.archived_at is not None
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
        archived_at=item.archived_at.isoformat() if item.archived_at else None,
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
