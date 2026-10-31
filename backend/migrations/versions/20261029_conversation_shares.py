"""URL conversation snapshots, expiry and revocation (no retained DOCX files)."""

import sqlalchemy as sa
from alembic import op

revision = "20261029_conversation_shares"
down_revision = "20261017_archive"


def upgrade():
    # The application also creates missing tables on startup; allow either order.
    if sa.inspect(op.get_bind()).has_table("workbench_conversation_shares"):
        return
    op.create_table(
        "workbench_conversation_shares",
        sa.Column("conversation_id", sa.String(100), primary_key=True),
        sa.Column("owner", sa.String(200), nullable=False),
        sa.Column("token", sa.String(36), nullable=False, unique=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("owner", "expires_at"):
        op.create_index(f"ix_workbench_conversation_shares_{column}", "workbench_conversation_shares", [column])


def downgrade():
    raise RuntimeError("Destructive downgrade is disabled. Restore a verified backup instead.")
