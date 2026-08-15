-- Migración incremental — tabla para el sistema de eventos dinámico
-- (transform/events.py, el "Automatizador" del motor ETL). Segura de
-- correr más de una vez (IF NOT EXISTS), no toca datos existentes.
--
-- Uso: docker compose exec postgres_dw psql -U cmms_admin -d cmms_dw -f /dev/stdin < migrations/003_eventos_automatizacion.sql

CREATE TABLE IF NOT EXISTS core.evento_automatizacion (
    evento_id       BIGSERIAL PRIMARY KEY,
    modulo             TEXT NOT NULL,          -- ej: equipos_sede_externa
    evento_nombre         TEXT NOT NULL,       -- ej: equipo_critico_nuevo (nombre en event_rules del config)
    record_key               TEXT,             -- clave del registro que disparó el evento (ej. codigo_activo)
    accion                     TEXT NOT NULL,  -- log | webhook | ...
    resultado                    TEXT,         -- ej: "registrado", "ok: 200", "error: ..."
    detalles                        JSONB,
    fecha                              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evento_automatizacion_fecha ON core.evento_automatizacion(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_evento_automatizacion_modulo ON core.evento_automatizacion(modulo, evento_nombre);

SELECT 'Migración 003 aplicada correctamente' AS resultado;
