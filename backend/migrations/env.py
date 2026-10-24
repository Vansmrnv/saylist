import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.core.db import Base, get_engine
from app.modules import load_all

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

load_all()
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    async with get_engine().connect() as connection:
        await connection.run_sync(_run)


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against a database.")
asyncio.run(_run_online())
