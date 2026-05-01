"""Alembic environment configuration.

The DB URL is sourced from ``AI_SCHOOL_DB_URL`` (matching the application's
``database.py``) so migrations always run against the same target the app
uses. We deliberately fail fast if the URL is missing rather than silently
falling back to a developer's SQLite file.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the ``ai_school`` package importable when alembic is run from the repo
# root. We avoid a hard dependency on the project being pip-installed.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_school.app.database import Base  # noqa: E402
from ai_school.app import models  # noqa: F401, E402  (registers metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    url = os.getenv("AI_SCHOOL_DB_URL", "").strip()
    if not url:
        raise RuntimeError(
            "AI_SCHOOL_DB_URL must be set when running alembic; refusing to "
            "guess a SQLite fallback because production uses PostgreSQL."
        )
    return url


def run_migrations_offline() -> None:
    """Render SQL to stdout without a live connection."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database engine."""
    cfg_section = config.get_section(config.config_ini_section) or {}
    cfg_section["sqlalchemy.url"] = _resolve_database_url()
    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
