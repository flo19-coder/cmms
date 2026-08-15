-- =============================================================
-- CAPA CORE — datos tipados, deduplicados, con jerarquía resuelta
-- Adaptado a contexto CLÍNICO: infraestructura crítica de planta física
-- (energía, climatización, bombeo, gases medicinales, eléctrico)
-- =============================================================
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.responsable (
    responsable_id       SERIAL PRIMARY KEY,
    codigo_externo        TEXT UNIQUE,
    nombre_completo        TEXT NOT NULL,
    rol                    TEXT,                    -- Ing. Electromecánico, Técnico Electricista, etc.
    email                   TEXT
);

-- =============================================================
-- Autenticación y roles de acceso a la webapp (distinto de
-- core.responsable, que es el "responsable" que aparece en las OTs;
-- un usuario del sistema puede o no coincidir con un responsable).
--
-- Roles:
--   ADMIN       — gestiona usuarios, acceso total
--   SUPERVISOR  — dashboard, kanban, vista árbol, reportes (solo lectura hoy)
--   TECNICO     — kanban, vista árbol, ficha de activo (ejecuta OTs)
--   OPERADOR    — panel de kiosco y escaneo QR (ya son de acceso público,
--                 este rol es para cuando se agregue acción de escritura,
--                 ej. "marcar tarea realizada")
-- =============================================================
CREATE TABLE IF NOT EXISTS core.usuario (
    usuario_id         SERIAL PRIMARY KEY,
    username              TEXT UNIQUE NOT NULL,
    password_hash           TEXT NOT NULL,
    nombre_completo            TEXT NOT NULL,
    rol                          TEXT NOT NULL CHECK (rol IN ('ADMIN','SUPERVISOR','TECNICO','OPERADOR')),
    responsable_id                 INTEGER REFERENCES core.responsable(responsable_id),
    activo                           BOOLEAN NOT NULL DEFAULT TRUE,
    creado_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_login                         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS core.proveedor (
    proveedor_id          SERIAL PRIMARY KEY,
    codigo_externo          TEXT UNIQUE,
    nombre                   TEXT NOT NULL,
    tipo_servicio             TEXT                  -- fabricante, servicio técnico, calibración, etc.
);

CREATE TABLE IF NOT EXISTS core.activo (
    activo_id             SERIAL PRIMARY KEY,
    codigo_activo           TEXT UNIQUE NOT NULL,
    nombre                    TEXT NOT NULL,
    fabricante                 TEXT,
    modelo                      TEXT,
    numero_serie                 TEXT,
    tipo_equipo                   TEXT,             -- ej: Generador Eléctrico, Chiller, Bomba de Vacío, Transformador
    clasificacion_riesgo           TEXT,             -- ej: Riesgo Alto/Medio/Bajo (criticidad para continuidad operativa)
    criticidad                       TEXT,           -- Muy Alta / Alta / Media / Baja
    ubicacion_path                    TEXT,          -- ej: 'CLINICA_INTL/Sede_Lima/Planta_de_Generacion_Electrica' (denormalizado, simple)
    -- Campos para integración FUTURA de planos de la clínica (nullable,
    -- no requeridos hoy). plano_referencia = nombre/ruta de la imagen del
    -- plano (ej. "sede_lima_piso13.png"); plano_pos_x/y = posición en %
    -- (0-100) sobre esa imagen, para dibujar un pin del activo encima.
    plano_referencia                   TEXT,
    plano_pos_x                         NUMERIC,
    plano_pos_y                          NUMERIC,
    foto_filename                         TEXT,          -- nombre de archivo en webapp/static/fotos_activos/
    nivel_2_sede                       TEXT,
    nivel_3_servicio                    TEXT,
    proveedor_nombre                     TEXT,
    fecha_compra                        DATE,
    fecha_ultima_calibracion              DATE,
    proxima_calibracion                    DATE,
    fuera_de_servicio                       BOOLEAN DEFAULT FALSE,
    habilitado                               BOOLEAN DEFAULT TRUE,
    plan_mantenimiento                        TEXT,
    horas_uso_promedio_diario                  NUMERIC,
    costo_compra                                 NUMERIC,
    valor_salvamento                              NUMERIC,
    vida_util_anios                                NUMERIC,
    -- Campos ficha estilo Fracttal (ver migrations/002_ficha_activo_fracttal.sql)
    clasificacion_1                                 TEXT,   -- ej: ENERGIA, CLIMATIZACION
    clasificacion_2                                  TEXT,   -- ej: norma/certificación aplicable
    numero_pedido                                     TEXT,
    codigo_barras                                      TEXT,
    visible_para_todos                                  BOOLEAN NOT NULL DEFAULT TRUE,
    moneda                                               TEXT NOT NULL DEFAULT 'PEN',
    formulario_personalizado                              JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at                                      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activo_sede_servicio ON core.activo(nivel_2_sede, nivel_3_servicio);
CREATE INDEX IF NOT EXISTS idx_activo_tipo ON core.activo(tipo_equipo);

-- Nota de diseño: las tablas de hechos referencian el activo por su
-- código natural (codigo_activo, FK a core.activo) en lugar de un ID
-- numérico interno. Esto evita una etapa extra de resolución de FKs
-- en el loader (que hace upsert directo por lotes) y es más simple de
-- mantener para el volumen de datos de este proyecto.
CREATE TABLE IF NOT EXISTS core.orden_trabajo (
    ot_id                  TEXT PRIMARY KEY,
    activo_codigo             TEXT REFERENCES core.activo(codigo_activo),
    responsable_nombre         TEXT,
    tipo_ot                      TEXT,               -- CORRECTIVO | PREVENTIVO | OVERHAUL | CALIBRACION
    descripcion_tarea              TEXT,
    estado                           TEXT,            -- Pendiente | En Proceso | En Revisión | Finalizada | Cancelada
    clasificacion_1                   TEXT,           -- ej: GESTION MECANICA, GESTION ELECTROMEDICA
    fecha_programada                    DATE,
    fecha_calculada                       DATE,
    fecha_realizacion                       DATE,
    porcentaje_avance                        NUMERIC DEFAULT 0,
    prioridad                                 TEXT,
    tiempo_fuera_servicio_horas                NUMERIC,   -- downtime clínico: crítico para reportes
    creado_por_usuario_id                       INTEGER REFERENCES core.usuario(usuario_id),
    creado_at                                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                                  TIMESTAMPTZ DEFAULT now(),
    origen                                        TEXT NOT NULL DEFAULT 'ETL'  -- 'ETL' (viene del pipeline demo/Fracttal) | 'MANUAL' (creada desde la webapp)
);
CREATE INDEX IF NOT EXISTS idx_ot_activo ON core.orden_trabajo(activo_codigo);
CREATE INDEX IF NOT EXISTS idx_ot_estado ON core.orden_trabajo(estado);

-- Auditoría: cada cambio de estado de una OT queda registrado (quién,
-- cuándo, de qué estado a qué estado). Necesario para que "transaccional"
-- signifique algo real y no solo "se pisa el campo estado".
CREATE TABLE IF NOT EXISTS core.orden_trabajo_historial (
    historial_id       SERIAL PRIMARY KEY,
    ot_id                  TEXT NOT NULL REFERENCES core.orden_trabajo(ot_id),
    estado_anterior           TEXT,
    estado_nuevo                TEXT NOT NULL,
    usuario_id                    INTEGER REFERENCES core.usuario(usuario_id),
    comentario                       TEXT,
    fecha_cambio                        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ot_historial_ot ON core.orden_trabajo_historial(ot_id, fecha_cambio);

CREATE TABLE IF NOT EXISTS core.tarea (
    tarea_id                TEXT PRIMARY KEY,
    activo_codigo               TEXT REFERENCES core.activo(codigo_activo),
    ot_id                        TEXT REFERENCES core.orden_trabajo(ot_id),
    nombre_tarea                   TEXT,
    planificada                      BOOLEAN DEFAULT TRUE,
    frecuencia                        TEXT,           -- ej: MENSUAL, TRIMESTRAL, SEMESTRAL, ANUAL
    fecha_programada                   DATE,
    estado                               TEXT,
    updated_at                            TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.medidor (
    medidor_id              TEXT PRIMARY KEY,
    activo_codigo               TEXT REFERENCES core.activo(codigo_activo),
    nombre_medidor                TEXT,
    tipo_variable                   TEXT,             -- Temperatura, Presión, Horas de Uso, Vibración...
    unidad                            TEXT,
    valor_umbral_alerta                 NUMERIC
);

CREATE TABLE IF NOT EXISTS core.lectura_medidor (
    lectura_id                BIGSERIAL PRIMARY KEY,
    medidor_id                   TEXT REFERENCES core.medidor(medidor_id),
    fecha_lectura                  TIMESTAMPTZ NOT NULL,
    valor                            NUMERIC NOT NULL,
    en_alerta                          BOOLEAN DEFAULT FALSE,
    UNIQUE (medidor_id, fecha_lectura)
);
CREATE INDEX IF NOT EXISTS idx_lectura_medidor_fecha ON core.lectura_medidor(medidor_id, fecha_lectura);

CREATE TABLE IF NOT EXISTS core.repuesto_almacen (
    repuesto_id                SERIAL PRIMARY KEY,
    codigo_repuesto               TEXT UNIQUE,
    nombre                          TEXT,
    almacen                           TEXT,
    stock_actual                       NUMERIC,
    stock_minimo                        NUMERIC,
    costo_unitario                       NUMERIC
);

-- Repuestos efectivamente usados en cada OT — necesario para mostrar
-- "repuestos usados" en la página de detalle del activo (escaneo QR).
CREATE TABLE IF NOT EXISTS core.ot_repuesto (
    id                SERIAL PRIMARY KEY,
    ot_id                TEXT REFERENCES core.orden_trabajo(ot_id),
    codigo_repuesto        TEXT REFERENCES core.repuesto_almacen(codigo_repuesto),
    cantidad                  NUMERIC DEFAULT 1,
    UNIQUE (ot_id, codigo_repuesto)
);

-- =============================================================
-- Ficha de activo estilo Fracttal — pestañas Terceros / Adjuntos /
-- Gestión Documental (ver migrations/002_ficha_activo_fracttal.sql)
-- =============================================================
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

CREATE TABLE IF NOT EXISTS core.activo_adjunto (
    adjunto_id           SERIAL PRIMARY KEY,
    activo_codigo           TEXT NOT NULL REFERENCES core.activo(codigo_activo) ON DELETE CASCADE,
    nombre_original             TEXT NOT NULL,
    archivo_filename              TEXT NOT NULL,
    tamano_bytes                    INTEGER,
    subido_por_usuario_id              INTEGER REFERENCES core.usuario(usuario_id),
    subido_at                             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activo_adjunto_activo ON core.activo_adjunto(activo_codigo);

CREATE TABLE IF NOT EXISTS core.activo_documento (
    documento_id          SERIAL PRIMARY KEY,
    activo_codigo             TEXT NOT NULL REFERENCES core.activo(codigo_activo) ON DELETE CASCADE,
    categoria                    TEXT NOT NULL DEFAULT 'Otro',  -- Manual | Certificado | Plano | Garantía | Otro
    nombre                          TEXT NOT NULL,
    archivo_filename                   TEXT NOT NULL,
    version                              TEXT,
    fecha_vigencia                          DATE,
    subido_por_usuario_id                      INTEGER REFERENCES core.usuario(usuario_id),
    subido_at                                     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_activo_documento_activo ON core.activo_documento(activo_codigo);

-- =============================================================
-- Sistema de eventos dinámico ("Automatizador") — ver
-- transform/events.py y migrations/003_eventos_automatizacion.sql
-- =============================================================
CREATE TABLE IF NOT EXISTS core.evento_automatizacion (
    evento_id       BIGSERIAL PRIMARY KEY,
    modulo             TEXT NOT NULL,
    evento_nombre         TEXT NOT NULL,
    record_key               TEXT,
    accion                     TEXT NOT NULL,
    resultado                    TEXT,
    detalles                        JSONB,
    fecha                              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evento_automatizacion_fecha ON core.evento_automatizacion(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_evento_automatizacion_modulo ON core.evento_automatizacion(modulo, evento_nombre);

-- =============================================================
-- AUDITORÍA REAL — log centralizado de eventos de todo el sistema
-- (no solo cambios de estado de OT, que ya tienen su propia tabla
-- core.orden_trabajo_historial más estructurada). Esto es el rastro
-- de "quién hizo qué" a nivel de todo el CMMS: logins, creación de
-- OTs, cambios de usuarios, incluso escaneos de QR.
-- =============================================================
CREATE TABLE IF NOT EXISTS core.auditoria (
    auditoria_id      BIGSERIAL PRIMARY KEY,
    usuario_id            INTEGER REFERENCES core.usuario(usuario_id),  -- NULL = evento anónimo (ej. escaneo QR sin login)
    accion                    TEXT NOT NULL,      -- LOGIN | LOGIN_FALLIDO | LOGOUT | CREAR_OT | CAMBIAR_ESTADO_OT |
                                                    -- FINALIZAR_OT | CREAR_USUARIO | DESACTIVAR_USUARIO | VER_ACTIVO_QR | ...
    entidad_tipo                TEXT,             -- 'orden_trabajo' | 'usuario' | 'activo' | NULL
    entidad_id                    TEXT,
    detalles                        JSONB,         -- info adicional específica de la acción
    ip_address                        TEXT,
    fecha                                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON core.auditoria(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON core.auditoria(usuario_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_accion ON core.auditoria(accion);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON core.auditoria(entidad_tipo, entidad_id);

-- =============================================================
-- CHECKLISTS DE MANTENIMIENTO — plantillas por tipo de equipo +
-- respuestas capturadas al finalizar una OT.
-- =============================================================
CREATE TABLE IF NOT EXISTS core.checklist_template (
    checklist_template_id  SERIAL PRIMARY KEY,
    nombre                     TEXT NOT NULL,
    tipo_equipo                   TEXT NOT NULL,   -- coincide con core.activo.tipo_equipo
    activo_bool                     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS core.checklist_template_item (
    item_id                SERIAL PRIMARY KEY,
    checklist_template_id     INTEGER NOT NULL REFERENCES core.checklist_template(checklist_template_id),
    orden                        INTEGER NOT NULL DEFAULT 0,
    descripcion                     TEXT NOT NULL,
    tipo_respuesta                     TEXT NOT NULL DEFAULT 'boolean' CHECK (tipo_respuesta IN ('boolean','numero','texto')),
    obligatorio                          BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_checklist_item_template ON core.checklist_template_item(checklist_template_id, orden);

CREATE TABLE IF NOT EXISTS core.ot_checklist_respuesta (
    respuesta_id          SERIAL PRIMARY KEY,
    ot_id                     TEXT NOT NULL REFERENCES core.orden_trabajo(ot_id),
    item_id                      INTEGER NOT NULL REFERENCES core.checklist_template_item(item_id),
    ok                              BOOLEAN,        -- resultado para items tipo 'boolean' (true=OK, false=falla)
    valor_numero                       NUMERIC,     -- para items tipo 'numero'
    valor_texto                           TEXT,     -- para items tipo 'texto'
    comentario                               TEXT,
    usuario_id                                  INTEGER REFERENCES core.usuario(usuario_id),
    fecha                                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ot_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_checklist_respuesta_ot ON core.ot_checklist_respuesta(ot_id);
