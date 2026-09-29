"""Credits ledger, daily usage rollup and top-up records.

与账号同库：扣费、记账与改余额必须在一个事务里。
"""

from alembic import op

from billing.models import CreditLedger, TopUp, UsageDaily
from infra.database import Base

revision = "20260929_billing"
down_revision = "20260929_accounts"


def upgrade():
    bind = op.get_bind()
    for model in (CreditLedger, UsageDaily, TopUp):
        model.__table__.create(bind, checkfirst=True)
    Base.metadata.create_all(bind)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
