-- Migración incremental — agrega lo necesario para que la ficha de
-- activo (/activo/<codigo>) tenga las mismas pestañas que la ficha de
-- Fracttal: Formulario Personalizado, Financiero, Terceros, Adjuntos y
-- Gestión Documental (además de General / Estado de Salud / Repuestos /
-- Historiales, que ya existían). Segura de correr más de una vez
-- (IF NOT EXISTS en todo) y no borra datos existentes.
--
-- Uso: docker compose exec postgres_dw psql -U cmms_admin -d cmms_dw -f /dev/stdin < migrations/002_ficha_activo_fracttal.sql

-- Campos nuevos en core.activo (pestaña General ampliada + Financiero)
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS clasificacion_1 TEXT;
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS clasificacion_2 TEXT;
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS numero_pedido TEXT;
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS codigo_barras TEXT;
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS visible_para_todos BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS moneda TEXT NOT NULL DEFAULT 'PEN';
ALTER TABLE core.activo ADD COLUMN IF NOT EXISTS formulario_personalizado JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Pestaña "Terceros" — proveedor / fabricante / servicio técnico / soporte
-- asociados a este activo (nombre + datos de contacto).
CREATE TABLE IF NOT EXISTS core.activo_tercero (
    tercero_id           SERIAL PRIMARY KEY,
    activo_codigo           TEXT NOT NULL REFERENCES core.activo(codigo_activo) ON DELETE CASCADE,
    tipo                       TEXT NOT NULL DEFAULT 'Proveedor',  -- Proveedor | Fabricante | Servicio Técnico | Soporte
    nombre                       TEXT NOT NULL,
    contacto_nombre                 TEXT,
    telefono                          TEXT,
    email                               TEXT,
    notas                                TEXT,
    creado_at                             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activo_tercero_activo ON core.activo_tercero(activo_codigo);

-- Pestaña "Adjuntos" — archivos sueltos (fotos adicionales, PDFs, etc.)
CREATE TABLE IF NOT EXISTS core.activo_adjunto (
    adjunto_id           SERIAL PRIMARY KEY,
    activo_codigo           TEXT NOT NULL REFERENCES core.activo(codigo_activo) ON DELETE CASCADE,
    nombre_original             TEXT NOT NULL,
    archivo_filename              TEXT NOT NULL,   -- nombre en webapp/static/adjuntos_activos/
    tamano_bytes                    INTEGER,
    subido_por_usuario_id              INTEGER REFERENCES core.usuario(usuario_id),
    subido_at                             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activo_adjunto_activo ON core.activo_adjunto(activo_codigo);

-- Pestaña "Gestión Documental" — documentos formales versionados
-- (manuales, certificados, planos, garantías), a diferencia de Adjuntos
-- que es solo un archivo suelto sin categoría/versión/vigencia.
CREATE TABLE IF NOT EXISTS core.activo_documento (
    documento_id          SERIAL PRIMARY KEY,
    activo_codigo             TEXT NOT NULL REFERENCES core.activo(codigo_activo) ON DELETE CASCADE,
    categoria                    TEXT NOT NULL DEFAULT 'Otro',  -- Manual | Certificado | Plano | Garantía | Otro
    nombre                          TEXT NOT NULL,
    archivo_filename                   TEXT NOT NULL,  -- nombre en webapp/static/documentos_activos/
    version                              TEXT,
    fecha_vigencia                          DATE,
    subido_por_usuario_id                      INTEGER REFERENCES core.usuario(usuario_id),
    subido_at                                     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activo_documento_activo ON core.activo_documento(activo_codigo);

-- mart.dim_activo ampliada con las 2 clasificaciones (útiles para Power BI)
-- Nota: Postgres exige que CREATE OR REPLACE VIEW agregue columnas nuevas
-- solo AL FINAL de la lista (no puede reordenar/insertar en medio) —
-- por eso clasificacion_1/2 van después de calibracion_vencida.
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

SELECT 'Migración 002 aplicada correctamente' AS resultado;
