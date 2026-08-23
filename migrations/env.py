"""Alembic environment for the PostgreSQL ingest schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from pixiv_yuri.acquisition import (
    persistence_models as acquisition_persistence_models,  # noqa: F401
)
from pixiv_yuri.analytics import models as analytics_models  # noqa: F401
from pixiv_yuri.api import persistence_models as api_persistence_models  # noqa: F401
from pixiv_yuri.ingest import models as ingest_models  # noqa: F401
from pixiv_yuri.jjwxc import persistence as jjwxc_persistence_models  # noqa: F401
from pixiv_yuri.shared.database import Base, normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

environment_url = os.getenv("PYURI_DATABASE_URL")
if environment_url:
    config.set_main_option(
        "sqlalchemy.url", normalize_database_url(environment_url).replace("%", "%%")
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate PostgreSQL SQL without opening a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with short pre-ping-enabled connections."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        pool_pre_ping=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
