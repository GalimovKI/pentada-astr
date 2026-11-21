from alembic import context
from mail_search.storage.database import open_database
from mail_search.storage.schema import metadata


def run(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with open_database() as engine, engine.connect() as connection:
        run(connection)
