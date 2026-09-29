"""Accounts and cloud sessions join the same database as workbench content.

账号搬到云端库的理由：计费要求「扣费 + 记账」和账号状态落在同一个事务里，
分居两套存储会让每次充值都变成跨库操作。这里是纯新增——工作台的四张表不动。

注意：revision 1 用的是 `Base.metadata.create_all`，那是幂等的，但它只覆盖当时
已注册的模型；已升级过的库不会自动多出这两张表，所以这里显式建表。
"""

from alembic import op

from infra.account_store import Account, AccountSession
from infra.database import Base

revision = "20260929_accounts"
down_revision = "20260928_workbench"


def upgrade():
    bind = op.get_bind()
    for model in (Account, AccountSession):
        model.__table__.create(bind, checkfirst=True)
    # 工作台的表若在这个全新库上还不存在（先跑了本 revision），一并补齐。
    Base.metadata.create_all(bind)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
