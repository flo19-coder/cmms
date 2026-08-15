-- Migración incremental — para bases YA corriendo que no tenían la
-- columna foto_filename. Es seguro correrla más de una vez (IF NOT EXISTS).
-- No borra ni toca datos existentes.
--
-- Uso: docker compose exec postgres_dw psql -U cmms_admin -d cmms_dw -f /dev/stdin < migrations/001_foto_activo.sql
-- (o pegarla directo en una sesión de psql interactiva)

ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS foto_filename TEXT;

CREATE OR REPLACE VIEW mart.dim_activo AS
SELECT
    a.activo_id,
    a.codigo_activo,
    a.nombre,
    a.fabricante,
    a.modelo,
    a.tipo_equipo,
    a.clasificacion_riesgo,
    a.criticidad,
    a.nivel_2_sede,
    a.nivel_3_servicio,
    a.proveedor_nombre,
    a.plano_referencia,
    a.plano_pos_x,
    a.plano_pos_y,
    a.foto_filename,
    a.fuera_de_servicio,
    a.habilitado,
    a.fecha_ultima_calibracion,
    a.proxima_calibracion,
    CASE WHEN a.proxima_calibracion < CURRENT_DATE THEN TRUE ELSE FALSE END AS calibracion_vencida
FROM core.activo a;

SELECT 'Migración 001 aplicada correctamente' AS resultado;
