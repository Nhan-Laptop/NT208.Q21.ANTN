from __future__ import annotations

import os
from urllib.parse import urlparse
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.core.database import Base
from app import models  # noqa: F401

config = context.config
configured_url = config.get_main_option("sqlalchemy.url")
if settings.alembic_database_url:
    config.set_main_option("sqlalchemy.url", settings.alembic_database_url)
elif not configured_url:
    config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if os.getenv("AIRA_ALEMBIC_DEBUG"):
        parsed = urlparse(url)
        print(
            "alembic_url",
            {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port, "database": parsed.path.lstrip("/")},
        )
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
