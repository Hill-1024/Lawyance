"""Initial cloud workbench schema."""

from alembic import op
from workbench.store import Base

revision = "20260928_workbench"
down_revision = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
