"""Login throttle joins the ledger's database.

登录失败节流从 data/lockout.json 搬进云端库：Redis 做快路径（计数与锁定标记），
Postgres 是事实源——进程重启、Redis 重启、多 worker 都不丢锁。
"""

from alembic import op

from infra.database import Base
from infra.throttle import LoginThrottle

revision = "20260929_throttle"
down_revision = "20260929_announcements"


def upgrade():
    bind = op.get_bind()
    LoginThrottle.__table__.create(bind, checkfirst=True)
    Base.metadata.create_all(bind)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is disabled. Restore a verified backup instead."
    )
