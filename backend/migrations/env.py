from alembic import context
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
