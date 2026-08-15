-- =============================================================
-- CAPA MART — modelo estrella listo para Power BI
-- (vistas materializadas sobre core; simples de refrescar)
-- =============================================================
CREATE SCHEMA IF NOT EXISTS mart;

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
    CASE WHEN a.proxima_calibracion < CURRENT_DATE THEN TRUE ELSE FALSE END AS calibracion_vencida,
    a.clasificacion_1,
    a.clasificacion_2
FROM core.activo a;
-- Nota: la ubicación (sede/servicio) va denormalizada directo en
-- core.activo (nivel_2_sede, nivel_3_servicio) en vez de en una tabla
-- separada — más simple para el volumen de datos de este proyecto.
-- dim_ubicacion como tabla aparte se puede reintroducir más adelante
-- si la jerarquía real de Fracttal necesita más de 2 niveles.

CREATE OR REPLACE VIEW mart.dim_responsable AS
SELECT * FROM core.responsable;

CREATE OR REPLACE VIEW mart.dim_tiempo AS
SELECT DISTINCT
    fecha::date AS fecha,
    EXTRACT(YEAR FROM fecha)::int AS anio,
    EXTRACT(MONTH FROM fecha)::int AS mes,
    TO_CHAR(fecha, 'Month') AS nombre_mes,
    EXTRACT(WEEK FROM fecha)::int AS semana_iso,
    EXTRACT(DOW FROM fecha)::int AS dia_semana
FROM generate_series(
    (SELECT MIN(fecha_programada) FROM core.orden_trabajo),
    (SELECT MAX(fecha_programada) FROM core.orden_trabajo) + INTERVAL '90 day',
    INTERVAL '1 day'
) AS fecha;

CREATE OR REPLACE VIEW mart.fact_orden_trabajo AS
SELECT
    ot.ot_id,
    ot.activo_codigo,
    a.activo_id,
    ot.responsable_nombre,
    ot.tipo_ot,
    ot.estado,
    ot.clasificacion_1,
    ot.fecha_programada,
    ot.fecha_calculada,
    ot.fecha_realizacion,
    ot.porcentaje_avance,
    ot.prioridad,
    ot.tiempo_fuera_servicio_horas,
    (ot.fecha_realizacion IS NOT NULL) AS finalizada,
    (ot.fecha_realizacion > ot.fecha_programada) AS atrasada
FROM core.orden_trabajo ot
LEFT JOIN core.activo a ON a.codigo_activo = ot.activo_codigo;

CREATE OR REPLACE VIEW mart.fact_lectura_medidor AS
SELECT
    lm.lectura_id,
    lm.medidor_id,
    m.activo_codigo,
    a.activo_id,
    m.tipo_variable,
    m.unidad,
    m.valor_umbral_alerta,
    lm.fecha_lectura,
    lm.valor,
    lm.en_alerta
FROM core.lectura_medidor lm
JOIN core.medidor m ON m.medidor_id = lm.medidor_id
LEFT JOIN core.activo a ON a.codigo_activo = m.activo_codigo;

-- KPI pre-calculado, análogo al dashboard de Fracttal visto en las capturas
CREATE OR REPLACE VIEW mart.kpi_dashboard AS
SELECT
    COUNT(*) FILTER (WHERE estado = 'En Proceso')  AS ots_en_proceso,
    COUNT(*) FILTER (WHERE estado = 'En Revisión')  AS ots_en_revision,
    COUNT(*) FILTER (WHERE estado = 'Finalizada')    AS ots_finalizadas,
    COUNT(*) FILTER (WHERE estado != 'Finalizada' AND fecha_programada < CURRENT_DATE) AS tareas_pendientes_con_atraso,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE estado = 'Finalizada') / NULLIF(COUNT(*), 0), 1
    ) AS porcentaje_cumplimiento
FROM core.orden_trabajo;
