from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from deepstack.db import Base, database_url

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=database_url(direct=True), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(database_url(direct=True), poolclass=NullPool).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
