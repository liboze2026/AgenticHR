"""Alembic env — 接入 AgenticHR app metadata."""
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from app.database import Base
from app.modules.auth.models import User  # noqa: F401 ensure models registered
from app.modules.resume.models import Resume  # noqa: F401
from app.modules.screening.models import Job  # noqa: F401
from app.modules.scheduling.models import Interviewer, Interview  # noqa: F401
from app.modules.notification.models import NotificationLog  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_override_url = os.environ.get("ALEMBIC_DB_URL") or os.environ.get("DATABASE_URL")
if _override_url:
    config.set_main_option("sqlalchemy.url", _override_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 支持
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
