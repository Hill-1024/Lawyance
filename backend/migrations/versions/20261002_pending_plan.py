"""Account pending plan change: 预约降级/切回按量，到结算日生效。

存量库加两列可空列即可（无回填）；唯一性不涉及。Postgres 与 sqlite 同一套
ADD COLUMN 写法（两列都可空，不存在 NOT NULL + 存量行的坑）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261002_pending_plan"
down_revision = "20261001_account_profile"


def _pg_columns(conn):
    return {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'accounts'"
            )
        )
    }


def _sqlite_columns(conn):
    return {row[1] for row in conn.execute(sa.text("PRAGMA table_info(accounts)"))}


def upgrade():
    conn = op.get_bind()
    existing = _sqlite_columns(conn) if conn.dialect.name == "sqlite" else _pg_columns(conn)
    if not existing:
        return
    for name, column_type in (
        ("pending_plan", sa.String(16)),
        ("pending_effective_at", sa.DateTime(timezone=True)),
    ):
        if name in existing:
            continue
        op.add_column("accounts", sa.Column(name, column_type, nullable=True))


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
