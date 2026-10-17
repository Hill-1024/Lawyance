"""Workbench archive semantics: 独立的 archived_at 列。

旧实现把归档写进 data["archived"]，但列表与搜索从不读它：用户点「归档」后，
条目只是从前端某一页里被过滤掉，服务端仍然把它当普通内容返回。这里把归档
提升为一等列，并把存量 JSON 标记回填过来。

回填值是 updated_at（当时归档也会刷新 updated_at），只用于排序，不追求精确。
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20261017_archive"
down_revision = "20261002_pending_plan"


def _columns(conn, table):
    if conn.dialect.name == "sqlite":
        return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}
    return {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        )
    }


def _legacy_flag(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return False
    return isinstance(value, dict) and bool(value.get("archived"))


def upgrade():
    conn = op.get_bind()
    columns = _columns(conn, "workbench_items")
    if not columns:
        return
    if "archived_at" not in columns:
        op.add_column(
            "workbench_items",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
    rows = conn.execute(
        sa.text("SELECT id, data FROM workbench_items WHERE archived_at IS NULL")
    ).fetchall()
    for identifier, data in rows:
        if not _legacy_flag(data):
            continue
        conn.execute(
            sa.text(
                "UPDATE workbench_items SET archived_at = updated_at "
                "WHERE id = :identifier"
            ),
            {"identifier": identifier},
        )


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
