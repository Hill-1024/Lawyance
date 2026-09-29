from alembic import context

# 导入所有模型模块，Base.metadata 才是完整的（否则 autogenerate 会误判要删表）。
from billing import models as billing_models  # noqa: F401
from infra import account_store  # noqa: F401
from infra import throttle as throttle_models  # noqa: F401
from workbench.store import Base, database_url, engine_for

if context.is_offline_mode():
    context.configure(
        url=database_url(), target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine_for(database_url()).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
