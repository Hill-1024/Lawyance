"""Opening announcements shown to signed-in accounts.

开屏公告是一张独立的新表：按套餐受众与生效时间窗口下发，不影响既有计费表。
与其它 revision 一样是纯新增——已升级过的库不会因为
`Base.metadata.create_all` 而自动多出这张表，所以这里显式建表。
"""

from alembic import op

from billing.models import Announcement
from infra.database import Base

revision = "20260929_announcements"
down_revision = "20260929_billing"


def upgrade():
    bind = op.get_bind()
    Announcement.__table__.create(bind, checkfirst=True)
    # 冷启动库上可能还缺更早 revision 的表（先跑了本 revision），一并补齐。
    Base.metadata.create_all(bind)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
