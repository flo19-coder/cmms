-- =============================================================
-- CAPA STAGING — datos crudos tal cual llegan del conector
-- (API real de Fracttal o generador demo, misma forma de dato)
-- =============================================================
CREATE SCHEMA IF NOT EXISTS staging;

-- Metadata técnica común a toda carga (trazabilidad de pipeline)
CREATE TABLE IF NOT EXISTS staging.batch_log (
    batch_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_name     TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'demo',   -- 'demo' | 'fracttal_api'
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    records_loaded  INTEGER,
    status          TEXT DEFAULT 'running'          -- running | success | failed
);

CREATE TABLE IF NOT EXISTS staging.stg_activos (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            UUID REFERENCES staging.batch_log(batch_id),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload         JSONB NOT NULL,
    codigo_activo       TEXT GENERATED ALWAYS AS (raw_payload->>'codigo') STORED,
    updated_at_source   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_stg_activos_codigo ON staging.stg_activos(codigo_activo);

CREATE TABLE IF NOT EXISTS staging.stg_ordenes_trabajo (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            UUID REFERENCES staging.batch_log(batch_id),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload         JSONB NOT NULL,
    ot_id               TEXT GENERATED ALWAYS AS (raw_payload->>'ot_id') STORED,
    updated_at_source   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_stg_ots_ot_id ON staging.stg_ordenes_trabajo(ot_id);

CREATE TABLE IF NOT EXISTS staging.stg_tareas (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            UUID REFERENCES staging.batch_log(batch_id),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload         JSONB NOT NULL,
    tarea_id            TEXT GENERATED ALWAYS AS (raw_payload->>'tarea_id') STORED,
    updated_at_source   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS staging.stg_medidores_lecturas (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            UUID REFERENCES staging.batch_log(batch_id),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload         JSONB NOT NULL,
    medidor_id          TEXT GENERATED ALWAYS AS (raw_payload->>'medidor_id') STORED,
    updated_at_source   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_stg_medidores_id ON staging.stg_medidores_lecturas(medidor_id);

CREATE TABLE IF NOT EXISTS staging.stg_almacenes (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            UUID REFERENCES staging.batch_log(batch_id),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload         JSONB NOT NULL,
    updated_at_source   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS staging.stg_recursos_humanos (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            UUID REFERENCES staging.batch_log(batch_id),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload         JSONB NOT NULL,
    updated_at_source   TIMESTAMPTZ
);
