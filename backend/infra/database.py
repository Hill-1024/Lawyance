"""
模块描述：全应用共用的数据库入口——引擎、会话工厂与声明式基类。

账号（auth）与工作台内容（workbench）现在是同一个库里的两张表，理由见
docs/workbench/operations.md：计费要求「扣费 + 记账」落在同一个事务里，
两套存储会让每次充值都变成跨库操作。生产用 PostgreSQL；SQLite 只允许测试时启用。

模块只在导入时读环境变量，不做连接；真正的连接由 engine_for 惰性建立并缓存。
"""

from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, sessionmaker


SQLITE_TESTING = "1"


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


def raw_database_url() -> str:
    """未做任何校验的原始配置，供启动阶段判断「是否已配置云端数据库」。"""
    return os.environ.get("LAWVER_DATABASE_URL", "").strip()


def derived_test_database() -> bool:
    """测试模式且未显式配库：database_url() 会按数据目录派生 sqlite。"""
    return not raw_database_url() and os.environ.get("LAWVER_WORKBENCH_TESTING") == SQLITE_TESTING


def cloud_database_ready() -> bool:
    """账号库是否可用（显式配置，或测试模式下可派生）。

    启动日志、工作台门禁都问这一个函数：此前门禁只看 LAWVER_DATABASE_URL，
    于是「账号能登录、工作台全 403」的半可用状态会在演示/验收实例上稳定复现。
    """
    return bool(raw_database_url()) or derived_test_database()


def database_url(message: str = "云端数据库尚未配置") -> str:
    """返回可直接交给 SQLAlchemy 的连接串；未配置或类型不合法时抛出可读错误。"""
    url = raw_database_url()
    if not url:
        if os.environ.get("LAWVER_WORKBENCH_TESTING") == SQLITE_TESTING:
            # 测试模式：按数据目录派生一个独立库。用例各自换 LAWVER_DATA_DIR，
            # 于是每个用例天然拿到干净、互不干扰的账号库。
            data_dir = os.environ.get("LAWVER_DATA_DIR") or "data"
            return "sqlite:///" + os.path.join(data_dir, "cloud.sqlite3")
        raise HTTPException(503, message)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+") and not (
        os.environ.get("LAWVER_WORKBENCH_TESTING") == SQLITE_TESTING
        and url.startswith("sqlite")
    ):
        raise RuntimeError("数据库需要 PostgreSQL（SQLite 仅在测试模式下允许）")
    return url


@lru_cache(maxsize=4)
def engine_for(url: str):
    return create_engine(
        url,
        pool_pre_ping=True,
        **(
            {"connect_args": {"check_same_thread": False}}
            if url.startswith("sqlite")
            else {}
        ),
    )


_SCHEMA_LOCK = threading.Lock()


def create_tables(engine, tables=None, *, metadata=None) -> None:
    """自愈建表（缺才建）的唯一入口。生产走 alembic，这里只兜「忘了迁移」与测试库。

    各模块的 ensure_tables 会在不同线程里同时触发（启动时账号引导在线程池里跑，工作台
    worker 认领任务又在另一个线程里建全部表）。checkfirst 是「先查后建」：并发时两边都
    查到没有、再一起 CREATE，输的一方报 table already exists——SQLite 抛 OperationalError，
    PostgreSQL 抛 ProgrammingError，后者账号引导接不住，会让启动直接失败。

    进程内用一把锁串行；跨进程（多 worker）撞上时再按 checkfirst 走一遍，对方已经建好的
    表会被跳过，真正的错误（连不上、没权限）第二遍照样抛出。
    """
    target = metadata if metadata is not None else Base.metadata
    selected = list(tables) if tables is not None else None
    with _SCHEMA_LOCK:
        try:
            target.create_all(engine, tables=selected, checkfirst=True)
        except DBAPIError:
            target.create_all(engine, tables=selected, checkfirst=True)


@contextmanager
def transaction(message: str = "云端数据库尚未配置"):
    """一个事务内的工作单元；退出即提交，异常即回滚。"""
    with sessionmaker(engine_for(database_url(message)), expire_on_commit=False)() as session:
        with session.begin():
            yield session
