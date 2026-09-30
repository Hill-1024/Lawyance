"""Account profile fields: uid, custom_id, avatar.

uid 是账号的稳定标识（对外引用一律用它），迁移时为存量账号回填；custom_id 是
用户自选的展示句柄；头像字节直接入库（accounts 量级小），version 做缓存失效。

Postgres 走 information_schema / ALTER TABLE；sqlite（测试派生库）走 PRAGMA +
ALTER TABLE。唯一性用唯一索引表达：两种库都支持「不存在才建」的幂等写法。
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20261001_account_profile"
down_revision = "20260929_throttle"

# (列名, DDL 类型, 是否可空, server_default)
COLUMNS = [
    ("uid", sa.String(32), False, None),
    ("custom_id", sa.String(32), True, None),
    ("avatar", sa.LargeBinary(), True, None),
    ("avatar_content_type", sa.String(40), True, None),
    ("avatar_version", sa.Integer(), False, "0"),
]

UNIQUE_INDEXES = [
    ("ux_accounts_uid", ["uid"]),
    ("ux_accounts_custom_id", ["custom_id"]),
]


def _pg_columns(conn: sa.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'accounts'"
            )
        )
    }


def _sqlite_columns(conn: sa.Connection) -> set[str]:
    return {row[1] for row in conn.execute(sa.text("PRAGMA table_info(accounts)"))}


def _backfill_uid(conn: sa.Connection) -> None:
    rows = conn.execute(
        sa.text("SELECT username FROM accounts WHERE uid IS NULL OR uid = ''")
    ).fetchall()
    for (username,) in rows:
        conn.execute(
            sa.text("UPDATE accounts SET uid = :uid WHERE username = :username"),
            {"uid": uuid.uuid4().hex, "username": username},
        )


def upgrade():
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"
    existing = _sqlite_columns(conn) if is_sqlite else _pg_columns(conn)
    # 表还没建（全新库）：ensure_tables/create_all 会按新模型直接建，无需补列。
    if not existing:
        return

    for name, column_type, nullable, server_default in COLUMNS:
        if name in existing:
            continue
        if is_sqlite:
            # sqlite 的 ADD COLUMN 不接受「NOT NULL 且无默认」；若给常量默认，回填前
            # 所有行同值，唯一索引也建不起来。uid 一律先加可空列、回填后靠唯一索引
            # 约束（新行由应用层保证必有 uid），avatar_version 的常量默认则没有歧义。
            force_not_null = not nullable and server_default is not None
            conn.execute(
                sa.text(
                    f"ALTER TABLE accounts ADD COLUMN {name} "
                    f"{column_type.compile(conn.dialect)}"
                    + (f" DEFAULT '{server_default}'" if server_default is not None else "")
                    + (" NOT NULL" if force_not_null else "")
                )
            )
        else:
            # Postgres 同理：存量行让 NOT NULL 直加会被拒（ADD COLUMN NOT NULL 立即
            # 校验，回填根本没机会跑）。uid 一律先可空、回填后补 SET NOT NULL；
            # 带 server_default 的列（avatar_version）可以直加。
            column = sa.Column(name, column_type, nullable=True, server_default=server_default)
            op.add_column("accounts", column)
            if not nullable and name == "uid":
                _backfill_uid(conn)
                op.alter_column("accounts", "uid", existing_type=sa.String(32), nullable=False)

    _backfill_uid(conn)
    conn.execute(
        sa.text("UPDATE accounts SET avatar_version = 0 WHERE avatar_version IS NULL")
    )
    for index_name, columns in UNIQUE_INDEXES:
        conn.execute(
            sa.text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                f"ON accounts ({', '.join(columns)})"
            )
        )


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
