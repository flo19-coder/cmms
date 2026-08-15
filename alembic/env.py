"""
Alembic -- desde acá en adelante, todo cambio de esquema pasa por una
migración versionada (ESPECIFICACION_CMMS_CODEX.md, regla global 6:
"Usa migraciones compatibles"). Las migraciones son SQL crudo vía
`op.execute()` (no ORM) para no forzar una reescritura de
infraestructura que todavía no se decidió.

La revisión baseline (`0001_baseline`) es un no-op: representa el
esquema YA creado por `sql/schema/*.sql` + `migrations/001-003.sql`
(aplicados antes de que existiera Alembic en este repo -- ver sección
10.5 de la especificación, "Estrategia de migración desde el esquema
actual"). `scripts/bootstrap_schema.py` aplica ese SQL y además hace
`alembic stamp head` en el mismo paso, así que cualquier base (nueva o
existente) queda "al día" sin volver a ejecutar DDL ya aplicado.

Conexión vía las mismas variables CMMS_DW_* que usa el resto del
proyecto -- nunca una URL con password hardcodeada en alembic.ini
(regla global 8).
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # sin ORM -- las migraciones son SQL crudo, no autogenerate


def _database_url() -> str:
    user = os.environ.get("CMMS_DW_USER", "cmms_admin")
    password = os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me")
    host = os.environ.get("CMMS_DW_HOST", "localhost")
    port = os.environ.get("CMMS_DW_PORT", "5432")
    name = os.environ.get("CMMS_DW_NAME", "cmms_dw")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
