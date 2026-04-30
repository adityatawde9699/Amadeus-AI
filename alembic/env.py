import asyncio

# Add Src to path to import models
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool, text as _sa_text
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context


sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import get_settings
from src.infra.persistence.orm_models import (
    Base,
)


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata
target_metadata = Base.metadata

# Set the SQLAlchemy URL from settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.get_async_database_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Acquire an advisory lock to prevent concurrent migration runs
    # (e.g. uvicorn --workers 4 all racing to run alembic upgrade head).
    # Lock ID 0xAMAD (42925) is arbitrary but unique to Amadeus.
    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        connection.execute(sa.text("SELECT pg_advisory_lock(42925)"))

    try:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if dialect_name == "postgresql":
            connection.execute(sa.text("SELECT pg_advisory_unlock(42925)"))



async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
