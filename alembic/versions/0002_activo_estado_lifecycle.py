"""Entrega 1 -- estado de ciclo de vida, fecha de instalación y notas en core.activo

Revision ID: 0002_activo_estado_lifecycle
Revises: 0001_baseline
Create Date: 2026-08-15

Agrega lo que el formulario de creación/edición de activos necesita y
que `habilitado`/`fuera_de_servicio` (booleanos ad-hoc, ya existentes)
no modelan bien: un estado de ciclo de vida explícito de 3 valores
(OPERATIVO / FUERA_DE_SERVICIO / RETIRADO). Los booleanos existentes se
mantienen (los usan queries/dashboard ya en producción) y se derivan
del estado nuevo desde el servicio de dominio -- ver
webapp/activos_servicio.py -- para no romper pantallas actuales
(regla global "mantén las pantallas actuales funcionando").
"""
from __future__ import annotations

from alembic import op

revision = "0002_activo_estado_lifecycle"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

ESTADOS = ("OPERATIVO", "FUERA_DE_SERVICIO", "RETIRADO")


def upgrade() -> None:
    op.execute("ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'OPERATIVO'")
    op.execute("ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS fecha_instalacion DATE")
    op.execute("ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS notas TEXT")

    # Backfill: activos existentes ya tenían fuera_de_servicio/habilitado --
    # se deriva 'estado' de esos valores para no dejar filas inconsistentes.
    op.execute(
        """
        UPDATE core.activo SET estado = CASE
            WHEN habilitado = FALSE THEN 'RETIRADO'
            WHEN fuera_de_servicio = TRUE THEN 'FUERA_DE_SERVICIO'
            ELSE 'OPERATIVO'
        END
        """
    )

    op.execute(
        f"""
        ALTER TABLE core.activo ADD CONSTRAINT chk_activo_estado
        CHECK (estado IN {ESTADOS})
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_activo_estado ON core.activo(estado)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.idx_activo_estado")
    op.execute("ALTER TABLE core.activo DROP CONSTRAINT IF EXISTS chk_activo_estado")
    op.execute("ALTER TABLE core.activo DROP COLUMN IF EXISTS notas")
    op.execute("ALTER TABLE core.activo DROP COLUMN IF EXISTS fecha_instalacion")
    op.execute("ALTER TABLE core.activo DROP COLUMN IF EXISTS estado")
