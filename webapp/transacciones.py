"""
Operaciones transaccionales sobre Órdenes de Trabajo.

Todo lo que cambia datos (crear OT, avanzar de estado, finalizar con
repuestos) pasa por acá — nunca directo desde una ruta de Flask — para
que la máquina de estados y el registro de auditoría (`core.orden_trabajo_historial`)
sean imposibles de saltarse por accidente.
"""
from __future__ import annotations

import uuid
from datetime import date

from db import transaction, query, query_one, DatabaseError
from auditoria import registrar_evento_en_cursor


class InvalidTransitionError(Exception):
    """Se intentó un cambio de estado que la máquina de estados no permite."""


class BusinessRuleError(Exception):
    """La operación viola una regla de negocio (ej. OT inexistente, repuesto sin stock)."""


# Máquina de estados — de qué estado se puede pasar a cuáles otros.
TRANSICIONES_VALIDAS: dict[str, list[str]] = {
    "Pendiente": ["En Proceso", "Cancelada"],
    "En Proceso": ["En Revisión", "Pendiente"],
    "En Revisión": ["Finalizada", "En Proceso"],
    "Finalizada": [],   # estado terminal
    "Cancelada": [],    # estado terminal
}

TIPOS_OT_VALIDOS = ["CORRECTIVO", "PREVENTIVO", "OVERHAUL", "CALIBRACION"]
PRIORIDADES_VALIDAS = ["Muy Alta", "Alta", "Media", "Baja"]


def _siguiente_ot_id() -> str:
    # Mismo formato que usa el generador demo (OT-XXXX-PS), pero con un
    # sufijo aleatorio corto para no colisionar con las OTs del ETL.
    return f"OT-M{uuid.uuid4().hex[:6].upper()}-PS"


def crear_orden_trabajo(
    *, activo_codigo: str, tipo_ot: str, descripcion_tarea: str,
    prioridad: str, fecha_programada: str, responsable_nombre: str | None,
    clasificacion_1: str | None, usuario_id: int, ip_address: str | None = None,
) -> dict:
    if tipo_ot not in TIPOS_OT_VALIDOS:
        raise BusinessRuleError(f"tipo_ot inválido: {tipo_ot}")
    if prioridad not in PRIORIDADES_VALIDAS:
        raise BusinessRuleError(f"prioridad inválida: {prioridad}")

    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (activo_codigo,))
    if not activo:
        raise BusinessRuleError(f"El activo '{activo_codigo}' no existe.")

    ot_id = _siguiente_ot_id()

    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO core.orden_trabajo
                (ot_id, activo_codigo, responsable_nombre, tipo_ot, descripcion_tarea,
                 estado, clasificacion_1, fecha_programada, fecha_calculada,
                 porcentaje_avance, prioridad, tiempo_fuera_servicio_horas,
                 creado_por_usuario_id, origen)
            VALUES (%s, %s, %s, %s, %s, 'Pendiente', %s, %s, %s, 0, %s, 0, %s, 'MANUAL')
            """,
            (ot_id, activo_codigo, responsable_nombre, tipo_ot, descripcion_tarea,
             clasificacion_1, fecha_programada, fecha_programada, prioridad, usuario_id),
        )
        cur.execute(
            "INSERT INTO core.orden_trabajo_historial (ot_id, estado_anterior, estado_nuevo, usuario_id, comentario) "
            "VALUES (%s, NULL, 'Pendiente', %s, 'OT creada')",
            (ot_id, usuario_id),
        )
        registrar_evento_en_cursor(
            cur, usuario_id=usuario_id, accion="CREAR_OT", entidad_tipo="orden_trabajo", entidad_id=ot_id,
            detalles={"activo_codigo": activo_codigo, "tipo_ot": tipo_ot, "prioridad": prioridad},
            ip_address=ip_address,
        )

    return {"ot_id": ot_id, "estado": "Pendiente"}


def cambiar_estado_ot(*, ot_id: str, nuevo_estado: str, usuario_id: int, comentario: str | None = None, ip_address: str | None = None) -> dict:
    ot = query_one("SELECT ot_id, estado FROM core.orden_trabajo WHERE ot_id = %s", (ot_id,))
    if not ot:
        raise BusinessRuleError(f"La OT '{ot_id}' no existe.")

    estado_actual = ot["estado"]
    permitidos = TRANSICIONES_VALIDAS.get(estado_actual, [])
    if nuevo_estado not in permitidos:
        raise InvalidTransitionError(
            f"No se puede pasar de '{estado_actual}' a '{nuevo_estado}'. "
            f"Transiciones válidas desde '{estado_actual}': {permitidos or '(ninguna, es estado terminal)'}"
        )

    avance = {"Pendiente": 0, "En Proceso": 50, "En Revisión": 100, "Finalizada": 100, "Cancelada": 0}[nuevo_estado]

    with transaction() as cur:
        cur.execute(
            "UPDATE core.orden_trabajo SET estado = %s, porcentaje_avance = %s, updated_at = now() WHERE ot_id = %s",
            (nuevo_estado, avance, ot_id),
        )
        cur.execute(
            "INSERT INTO core.orden_trabajo_historial (ot_id, estado_anterior, estado_nuevo, usuario_id, comentario) "
            "VALUES (%s, %s, %s, %s, %s)",
            (ot_id, estado_actual, nuevo_estado, usuario_id, comentario),
        )
        registrar_evento_en_cursor(
            cur, usuario_id=usuario_id, accion="CAMBIAR_ESTADO_OT", entidad_tipo="orden_trabajo", entidad_id=ot_id,
            detalles={"estado_anterior": estado_actual, "estado_nuevo": nuevo_estado},
            ip_address=ip_address,
        )

    return {"ot_id": ot_id, "estado_anterior": estado_actual, "estado_nuevo": nuevo_estado}


def get_checklist_para_activo(codigo_activo: str) -> dict | None:
    """
    Busca la plantilla de checklist activa que corresponda al tipo de
    equipo del activo. Devuelve None si no hay plantilla definida para
    ese tipo (no todos los tipos de equipo tienen checklist todavía).
    """
    activo = query_one("SELECT tipo_equipo FROM core.activo WHERE codigo_activo = %s", (codigo_activo,))
    if not activo:
        return None
    template = query_one(
        "SELECT checklist_template_id, nombre, tipo_equipo FROM core.checklist_template "
        "WHERE tipo_equipo = %s AND activo_bool = TRUE LIMIT 1",
        (activo["tipo_equipo"],),
    )
    if not template:
        return None
    items = query(
        "SELECT item_id, orden, descripcion, tipo_respuesta, obligatorio "
        "FROM core.checklist_template_item WHERE checklist_template_id = %s ORDER BY orden",
        (template["checklist_template_id"],),
    )
    template["checklist_items"] = items
    return template


def finalizar_ot(
    *, ot_id: str, usuario_id: int, repuestos: list[dict] | None = None,
    checklist_respuestas: list[dict] | None = None, comentario: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """
    Finaliza una OT y, en la MISMA transacción: registra los repuestos
    usados, descuenta su stock, guarda las respuestas del checklist de
    mantenimiento (si aplica), y deja el registro de auditoría. Si el
    stock de cualquier repuesto no alcanza, si falta un ítem obligatorio
    del checklist, o si cualquier paso falla, se revierte TODO.

    repuestos: [{"codigo_repuesto": "REP-001", "cantidad": 2}, ...]
    checklist_respuestas: [{"item_id": 5, "ok": true, "comentario": "..."},
                            {"item_id": 6, "valor_numero": 82.5}, ...]
    """
    repuestos = repuestos or []
    checklist_respuestas = checklist_respuestas or []
    ot = query_one("SELECT ot_id, activo_codigo, estado FROM core.orden_trabajo WHERE ot_id = %s", (ot_id,))
    if not ot:
        raise BusinessRuleError(f"La OT '{ot_id}' no existe.")

    estado_actual = ot["estado"]
    if "Finalizada" not in TRANSICIONES_VALIDAS.get(estado_actual, []):
        raise InvalidTransitionError(
            f"No se puede finalizar una OT en estado '{estado_actual}'. "
            f"Debe estar en 'En Revisión'."
        )

    # Si hay checklist definido para este tipo de equipo, los ítems
    # obligatorios DEBEN venir contestados — si no, no se finaliza.
    template = get_checklist_para_activo(ot["activo_codigo"])
    if template:
        obligatorios = {i["item_id"] for i in template["checklist_items"] if i["obligatorio"]}
        contestados = {r["item_id"] for r in checklist_respuestas}
        faltantes = obligatorios - contestados
        if faltantes:
            nombres = [i["descripcion"] for i in template["checklist_items"] if i["item_id"] in faltantes]
            raise BusinessRuleError(f"Faltan ítems obligatorios del checklist: {', '.join(nombres)}")

    with transaction() as cur:
        cur.execute(
            "UPDATE core.orden_trabajo SET estado = 'Finalizada', porcentaje_avance = 100, "
            "fecha_realizacion = %s, updated_at = now() WHERE ot_id = %s",
            (date.today().isoformat(), ot_id),
        )
        cur.execute(
            "INSERT INTO core.orden_trabajo_historial (ot_id, estado_anterior, estado_nuevo, usuario_id, comentario) "
            "VALUES (%s, %s, 'Finalizada', %s, %s)",
            (ot_id, estado_actual, usuario_id, comentario),
        )

        for rep in repuestos:
            codigo = rep["codigo_repuesto"]
            cantidad = rep["cantidad"]

            cur.execute("SELECT stock_actual FROM core.repuesto_almacen WHERE codigo_repuesto = %s FOR UPDATE", (codigo,))
            row = cur.fetchone()
            if not row:
                raise BusinessRuleError(f"El repuesto '{codigo}' no existe.")
            if row["stock_actual"] < cantidad:
                raise BusinessRuleError(
                    f"Stock insuficiente de '{codigo}': hay {row['stock_actual']}, se pidieron {cantidad}."
                )

            cur.execute(
                "INSERT INTO core.ot_repuesto (ot_id, codigo_repuesto, cantidad) VALUES (%s, %s, %s) "
                "ON CONFLICT (ot_id, codigo_repuesto) DO UPDATE SET cantidad = EXCLUDED.cantidad",
                (ot_id, codigo, cantidad),
            )
            cur.execute(
                "UPDATE core.repuesto_almacen SET stock_actual = stock_actual - %s WHERE codigo_repuesto = %s",
                (cantidad, codigo),
            )

        for resp in checklist_respuestas:
            cur.execute(
                """
                INSERT INTO core.ot_checklist_respuesta (ot_id, item_id, ok, valor_numero, valor_texto, comentario, usuario_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ot_id, item_id) DO UPDATE SET
                    ok = EXCLUDED.ok, valor_numero = EXCLUDED.valor_numero,
                    valor_texto = EXCLUDED.valor_texto, comentario = EXCLUDED.comentario
                """,
                (ot_id, resp["item_id"], resp.get("ok"), resp.get("valor_numero"),
                 resp.get("valor_texto"), resp.get("comentario"), usuario_id),
            )

        registrar_evento_en_cursor(
            cur, usuario_id=usuario_id, accion="FINALIZAR_OT", entidad_tipo="orden_trabajo", entidad_id=ot_id,
            detalles={
                "repuestos_registrados": len(repuestos),
                "checklist_items_respondidos": len(checklist_respuestas),
                "tenia_checklist": template is not None,
            },
            ip_address=ip_address,
        )

    return {"ot_id": ot_id, "estado": "Finalizada", "repuestos_registrados": len(repuestos)}


def get_historial_ot(ot_id: str) -> list[dict]:
    return query(
        """
        SELECT h.estado_anterior, h.estado_nuevo, h.comentario, h.fecha_cambio,
               u.nombre_completo AS usuario_nombre
        FROM core.orden_trabajo_historial h
        LEFT JOIN core.usuario u ON u.usuario_id = h.usuario_id
        WHERE h.ot_id = %s
        ORDER BY h.fecha_cambio ASC
        """,
        (ot_id,),
    )


def get_checklist_respuestas_ot(ot_id: str) -> list[dict]:
    return query(
        """
        SELECT i.descripcion, i.tipo_respuesta, r.ok, r.valor_numero, r.valor_texto,
               r.comentario, r.fecha, u.nombre_completo AS usuario_nombre
        FROM core.ot_checklist_respuesta r
        JOIN core.checklist_template_item i ON i.item_id = r.item_id
        LEFT JOIN core.usuario u ON u.usuario_id = r.usuario_id
        WHERE r.ot_id = %s
        ORDER BY i.orden
        """,
        (ot_id,),
    )
