"""baseline -- esquema ya creado por sql/schema/*.sql + migrations/001-003

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-15

No-op a propósito: representa el estado del esquema en el momento de
introducir Alembic en el proyecto (ver ESPECIFICACION_CMMS_CODEX.md,
sección 10.5, "Estrategia de migración desde el esquema actual", paso
2: "Introducir Alembic y registrar el esquema existente como baseline
sin recrearlo"). `scripts/bootstrap_schema.py` aplica sql/schema/*.sql
y luego hace `alembic stamp head` -- así cualquier base (nueva o
existente) queda marcada en esta revisión sin volver a ejecutar el DDL
que ya se aplicó. Toda migración NUEVA a partir de acá debe encadenar
`down_revision` desde esta.
"""
from __future__ import annotations

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
