"""
Consultas de negocio — una sola implementación, consumida tanto por las
vistas HTML (app.py) como por la API REST (api.py). Evita que HTML y API
devuelvan datos distintos para la "misma" información.

Cada función devuelve estructuras planas (dict/list) listas tanto para
render_template() como para jsonify().
"""
from __future__ import annotations

from datetime import date

from db import query, query_one, execute


class NotFoundError(Exception):
    """El recurso solicitado (ej. un activo) no existe."""


def get_dashboard_data() -> dict:
    kpi = query_one("SELECT * FROM mart.kpi_dashboard") or {}
    ots_por_tipo = query(
        "SELECT tipo_ot, COUNT(*) AS n FROM core.orden_trabajo GROUP BY tipo_ot ORDER BY n DESC"
    )
    activos_por_criticidad = query(
        "SELECT criticidad, COUNT(*) AS n FROM core.activo GROUP BY criticidad "
        "ORDER BY CASE criticidad WHEN 'Muy Alta' THEN 0 WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 ELSE 3 END"
    )
    activos_por_servicio = query(
        "SELECT nivel_3_servicio, COUNT(*) AS n FROM core.activo GROUP BY nivel_3_servicio ORDER BY n DESC"
    )
    inspecciones_vencidas = query(
        """
        SELECT codigo_activo, nombre, nivel_2_sede, nivel_3_servicio, proxima_calibracion
        FROM mart.dim_activo WHERE calibracion_vencida = TRUE
        ORDER BY proxima_calibracion ASC LIMIT 10
        """
    )
    stock_bajo = query(
        "SELECT codigo_repuesto, nombre, stock_actual, stock_minimo FROM core.repuesto_almacen "
        "WHERE stock_actual < stock_minimo ORDER BY (stock_minimo - stock_actual) DESC"
    )
    downtime_total = query_one(
        "SELECT COALESCE(SUM(tiempo_fuera_servicio_horas),0) AS horas FROM core.orden_trabajo"
    )
    return {
        "kpi": kpi,
        "ots_por_tipo": ots_por_tipo,
        "activos_por_criticidad": activos_por_criticidad,
        "activos_por_servicio": activos_por_servicio,
        "inspecciones_vencidas": inspecciones_vencidas,
        "stock_bajo": stock_bajo,
        "downtime_total": (downtime_total or {}).get("horas", 0),
    }


def get_vista_arbol_data() -> dict:
    activos = query(
        "SELECT codigo_activo, nombre, tipo_equipo, criticidad, fuera_de_servicio, "
        "nivel_2_sede, nivel_3_servicio FROM mart.dim_activo "
        "WHERE nivel_2_sede = 'Sede Lima' "
        "ORDER BY nivel_2_sede, nivel_3_servicio, nombre"
    )
    arbol: dict = {}
    for a in activos:
        sede = a["nivel_2_sede"] or "Sin sede"
        servicio = a["nivel_3_servicio"] or "Sin área"
        arbol.setdefault(sede, {}).setdefault(servicio, []).append(a)
    return arbol


def get_kanban_data() -> dict:
    ots = query(
        """
        SELECT o.ot_id, o.activo_codigo, a.nombre AS nombre_activo, a.nivel_2_sede, a.nivel_3_servicio,
               o.responsable_nombre, o.tipo_ot, o.estado, o.prioridad, o.descripcion_tarea,
               o.fecha_programada, o.porcentaje_avance
        FROM core.orden_trabajo o
        LEFT JOIN core.activo a ON a.codigo_activo = o.activo_codigo
        ORDER BY o.fecha_programada DESC
        LIMIT 200
        """
    )
    columnas = {"Pendiente": [], "En Proceso": [], "En Revisión": [], "Finalizada": []}
    for o in ots:
        columnas.setdefault(o["estado"], []).append(o)
    return columnas


def get_tareas_pendientes_kanban(limit: int = 100) -> list[dict]:
    """
    Columna "Tareas Pendientes" del Kanban (ver captura del manual
    Fracttal) — tareas que todavía no se convierten en una OT.
    """
    return query(
        """
        SELECT t.tarea_id, t.nombre_tarea, t.frecuencia, t.fecha_programada, t.activo_codigo,
               a.nombre AS nombre_activo, a.nivel_2_sede, a.nivel_3_servicio, a.criticidad
        FROM core.tarea t
        LEFT JOIN core.activo a ON a.codigo_activo = t.activo_codigo
        WHERE t.estado = 'Pendiente'
        ORDER BY t.fecha_programada
        LIMIT %s
        """,
        (limit,),
    )


def get_panel_hoy_data() -> dict:
    hoy = date.today().isoformat()
    ots_hoy = query(
        """
        SELECT o.ot_id, o.activo_codigo, a.nombre AS nombre_activo, a.nivel_2_sede, a.nivel_3_servicio,
               o.responsable_nombre, o.tipo_ot, o.estado, o.prioridad, o.descripcion_tarea
        FROM core.orden_trabajo o
        LEFT JOIN core.activo a ON a.codigo_activo = o.activo_codigo
        WHERE o.fecha_programada = %s
        ORDER BY CASE o.prioridad WHEN 'Muy Alta' THEN 0 WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 ELSE 3 END
        """,
        (hoy,),
    )
    tareas_hoy = query(
        """
        SELECT t.tarea_id, t.activo_codigo, a.nombre AS nombre_activo, a.nivel_2_sede, a.nivel_3_servicio,
               t.nombre_tarea, t.frecuencia, t.estado
        FROM core.tarea t
        LEFT JOIN core.activo a ON a.codigo_activo = t.activo_codigo
        WHERE t.fecha_programada = %s
        ORDER BY a.nivel_3_servicio
        """,
        (hoy,),
    )
    return {"hoy": hoy, "ots_hoy": ots_hoy, "tareas_hoy": tareas_hoy}


def get_activos_list(sede: str | None = None, servicio: str | None = None, criticidad: str | None = None) -> list[dict]:
    sql = (
        "SELECT codigo_activo, nombre, tipo_equipo, nivel_2_sede, nivel_3_servicio, criticidad "
        "FROM mart.dim_activo WHERE 1=1"
    )
    params: list = []
    if sede:
        sql += " AND nivel_2_sede = %s"
        params.append(sede)
    if servicio:
        sql += " AND nivel_3_servicio = %s"
        params.append(servicio)
    if criticidad:
        sql += " AND criticidad = %s"
        params.append(criticidad)
    sql += " ORDER BY nivel_2_sede, nivel_3_servicio, codigo_activo"
    return query(sql, tuple(params))


def get_activo_terceros(codigo: str) -> list[dict]:
    return query(
        "SELECT tercero_id, tipo, nombre, contacto_nombre, telefono, email, notas, creado_at "
        "FROM core.activo_tercero WHERE activo_codigo = %s ORDER BY creado_at DESC",
        (codigo,),
    )


def get_activo_adjuntos(codigo: str) -> list[dict]:
    return query(
        "SELECT adjunto_id, nombre_original, archivo_filename, tamano_bytes, subido_at "
        "FROM core.activo_adjunto WHERE activo_codigo = %s ORDER BY subido_at DESC",
        (codigo,),
    )


def get_activo_documentos(codigo: str) -> list[dict]:
    return query(
        "SELECT documento_id, categoria, nombre, archivo_filename, version, fecha_vigencia, subido_at "
        "FROM core.activo_documento WHERE activo_codigo = %s ORDER BY subido_at DESC",
        (codigo,),
    )


def _calcular_financiero(activo: dict) -> dict | None:
    """
    Depreciación lineal simple: (costo - valor de salvamento) / vida útil
    en años = depreciación anual. Con eso se estima el valor en libros
    actual a partir de los años transcurridos desde la compra.
    """
    costo = activo.get("costo_compra")
    vida_util = activo.get("vida_util_anios")
    if not costo or not vida_util:
        return None
    salvamento = float(activo.get("valor_salvamento") or 0)
    costo = float(costo)
    vida_util = float(vida_util)
    depreciacion_anual = (costo - salvamento) / vida_util
    anios_transcurridos = 0.0
    if activo.get("fecha_compra"):
        anios_transcurridos = (date.today() - activo["fecha_compra"]).days / 365.25
    valor_actual = max(salvamento, costo - depreciacion_anual * anios_transcurridos)
    return {
        "depreciacion_anual": round(depreciacion_anual, 2),
        "anios_transcurridos": round(anios_transcurridos, 1),
        "valor_actual_estimado": round(valor_actual, 2),
        "porcentaje_depreciado": round(100 * (1 - valor_actual / costo), 1) if costo else 0,
    }


def get_tareas_list(estado: str | None = None) -> list[dict]:
    sql = (
        "SELECT t.tarea_id, t.activo_codigo, a.nombre AS nombre_activo, a.nivel_2_sede, a.nivel_3_servicio, "
        "t.nombre_tarea, t.frecuencia, t.fecha_programada, t.estado, t.planificada "
        "FROM core.tarea t LEFT JOIN core.activo a ON a.codigo_activo = t.activo_codigo WHERE 1=1"
    )
    params: list = []
    if estado:
        sql += " AND t.estado = %s"
        params.append(estado)
    sql += " ORDER BY t.fecha_programada DESC NULLS LAST LIMIT 300"
    return query(sql, tuple(params))


def get_calendario_eventos(desde: str, hasta: str) -> list[dict]:
    """
    Eventos combinados (Tareas + Órdenes de Trabajo) para las vistas
    Calendario y Gantt — misma fuente de datos para ambas.

    `fecha_fin` no existe como tal en el esquema (ni tarea ni OT tienen
    una fecha de término planificada), así que se estima:
      - Tarea: bloque de 1 día (fecha_programada -> +1 día).
      - OT: si tiene `fecha_calculada` posterior a `fecha_programada`, se
        usa esa como fin; si no, también un bloque mínimo de 1 día. Esto
        es una estimación visual para el Gantt, no una fecha de término
        real — al arrastrar una barra se reprograma `fecha_programada`
        (y la duración estimada se recalcula igual).
    """
    tareas = query(
        """
        SELECT t.tarea_id AS id, 'tarea' AS tipo, t.nombre_tarea AS titulo,
               t.fecha_programada AS fecha_inicio,
               (t.fecha_programada + INTERVAL '1 day')::date AS fecha_fin,
               t.estado, t.activo_codigo, a.nombre AS nombre_activo, NULL AS prioridad
        FROM core.tarea t
        LEFT JOIN core.activo a ON a.codigo_activo = t.activo_codigo
        WHERE t.fecha_programada BETWEEN %s AND %s
        """,
        (desde, hasta),
    )
    ots = query(
        """
        SELECT o.ot_id AS id, 'ot' AS tipo, (o.ot_id || ' — ' || o.tipo_ot) AS titulo,
               o.fecha_programada AS fecha_inicio,
               GREATEST(COALESCE(o.fecha_calculada, o.fecha_programada), o.fecha_programada + INTERVAL '1 day')::date AS fecha_fin,
               o.estado, o.activo_codigo, a.nombre AS nombre_activo, o.prioridad
        FROM core.orden_trabajo o
        LEFT JOIN core.activo a ON a.codigo_activo = o.activo_codigo
        WHERE o.fecha_programada BETWEEN %s AND %s
        """,
        (desde, hasta),
    )
    return tareas + ots


def mover_evento_calendario(tipo: str, evento_id: str, nueva_fecha: str) -> None:
    if tipo == "tarea":
        execute("UPDATE core.tarea SET fecha_programada = %s, updated_at = now() WHERE tarea_id = %s",
                (nueva_fecha, evento_id))
    elif tipo == "ot":
        execute("UPDATE core.orden_trabajo SET fecha_programada = %s, fecha_calculada = %s, updated_at = now() WHERE ot_id = %s",
                (nueva_fecha, nueva_fecha, evento_id))
    else:
        raise ValueError(f"Tipo de evento desconocido: {tipo}")


def get_activo_detalle(codigo: str) -> dict:
    activo = query_one(
        """
        SELECT a.*,
               CASE WHEN a.proxima_calibracion < CURRENT_DATE THEN TRUE ELSE FALSE END AS calibracion_vencida
        FROM core.activo a WHERE a.codigo_activo = %s
        """,
        (codigo,),
    )
    if not activo:
        raise NotFoundError(f"Activo '{codigo}' no existe.")

    # Horas de uso ESTIMADAS a partir de reportes anteriores: horas/día
    # promedio x días transcurridos desde la compra. Es una estimación
    # (no un contador real de horómetro).
    horas_estimadas = None
    if activo.get("fecha_compra") and activo.get("horas_uso_promedio_diario"):
        dias = (date.today() - activo["fecha_compra"]).days
        horas_estimadas = round(dias * float(activo["horas_uso_promedio_diario"]))

    historial = query(
        """
        SELECT ot_id, tipo_ot, estado, fecha_programada, fecha_realizacion,
               porcentaje_avance, prioridad, tiempo_fuera_servicio_horas
        FROM core.orden_trabajo
        WHERE activo_codigo = %s
        ORDER BY fecha_programada DESC
        LIMIT 15
        """,
        (codigo,),
    )

    # Estado "apto" = última OT finalizada sin atraso; si la última OT
    # está pendiente/en proceso, el equipo queda "en atención".
    ultimo_estado = "Sin historial"
    if historial:
        u = historial[0]
        if u["estado"] == "Finalizada":
            atrasada = bool(u["fecha_realizacion"] and u["fecha_programada"] and u["fecha_realizacion"] > u["fecha_programada"])
            ultimo_estado = "APTO CON OBSERVACIÓN" if atrasada else "APTO"
        else:
            ultimo_estado = "EN ATENCIÓN"

    repuestos_usados = query(
        """
        SELECT r.nombre, r.codigo_repuesto, otr.cantidad, o.ot_id, o.fecha_programada
        FROM core.ot_repuesto otr
        JOIN core.repuesto_almacen r ON r.codigo_repuesto = otr.codigo_repuesto
        JOIN core.orden_trabajo o ON o.ot_id = otr.ot_id
        WHERE o.activo_codigo = %s
        ORDER BY o.fecha_programada DESC
        LIMIT 20
        """,
        (codigo,),
    )

    stats = query_one(
        """
        SELECT
            COUNT(*) AS total_ots,
            COUNT(*) FILTER (WHERE estado = 'Finalizada') AS finalizadas,
            ROUND(100.0 * COUNT(*) FILTER (WHERE estado = 'Finalizada') / NULLIF(COUNT(*), 0), 1) AS pct_finalizadas,
            COALESCE(SUM(tiempo_fuera_servicio_horas), 0) AS horas_downtime_total,
            COUNT(*) FILTER (WHERE tipo_ot = 'CORRECTIVO') AS total_correctivos
        FROM core.orden_trabajo WHERE activo_codigo = %s
        """,
        (codigo,),
    ) or {}

    lecturas = query(
        """
        SELECT fecha_lectura, valor, en_alerta
        FROM mart.fact_lectura_medidor
        WHERE activo_codigo = %s
        ORDER BY fecha_lectura DESC LIMIT 10
        """,
        (codigo,),
    )

    return {
        "activo": activo,
        "ubicacion_path": activo.get("ubicacion_path"),
        "plan_mantenimiento": activo.get("plan_mantenimiento"),
        "horas_estimadas": horas_estimadas,
        "historial": historial,
        "ultimo_estado": ultimo_estado,
        "repuestos_usados": repuestos_usados,
        "stats": stats,
        "lecturas": lecturas,
        "terceros": get_activo_terceros(codigo),
        "adjuntos": get_activo_adjuntos(codigo),
        "documentos": get_activo_documentos(codigo),
        "financiero": _calcular_financiero(activo),
    }
