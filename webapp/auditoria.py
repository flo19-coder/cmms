"""
Auditoría real — log centralizado de "quién hizo qué, cuándo, desde
dónde" para todo el sistema. No confundir con
`core.orden_trabajo_historial` (esa es específica de OTs, con columnas
estructuradas estado_anterior/estado_nuevo). Esta es genérica y cubre
también logins, gestión de usuarios, y escaneos de QR.
"""
from __future__ import annotations

import json
import logging

from db import query, execute

logger = logging.getLogger("cmms.auditoria")


def registrar_evento(
    *, usuario_id: int | None, accion: str,
    entidad_tipo: str | None = None, entidad_id: str | None = None,
    detalles: dict | None = None, ip_address: str | None = None,
) -> None:
    """
    Registra un evento de auditoría. Deliberadamente NO lanza excepción
    si falla — un problema de auditoría no debe tumbar la operación de
    negocio que la originó (se loguea el error y se sigue).
    """
    try:
        execute(
            "INSERT INTO core.auditoria (usuario_id, accion, entidad_tipo, entidad_id, detalles, ip_address) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (usuario_id, accion, entidad_tipo, entidad_id, json.dumps(detalles) if detalles else None, ip_address),
        )
    except Exception:
        logger.exception("No se pudo registrar evento de auditoría: accion=%s", accion)


def registrar_evento_en_cursor(
    cur, *, usuario_id: int | None, accion: str,
    entidad_tipo: str | None = None, entidad_id: str | None = None,
    detalles: dict | None = None, ip_address: str | None = None,
) -> None:
    """
    Igual que registrar_evento() pero usando un cursor ya abierto dentro
    de una transacción existente (ej. dentro de db.transaction() en
    transacciones.py) — así el registro de auditoría es parte de la
    MISMA transacción atómica que la operación que audita: si la
    operación se revierte, el registro de auditoría también.
    """
    cur.execute(
        "INSERT INTO core.auditoria (usuario_id, accion, entidad_tipo, entidad_id, detalles, ip_address) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (usuario_id, accion, entidad_tipo, entidad_id, json.dumps(detalles) if detalles else None, ip_address),
    )


def get_eventos(
    *, accion: str | None = None, usuario_id: int | None = None,
    entidad_tipo: str | None = None, limit: int = 200,
) -> list[dict]:
    sql = (
        "SELECT a.auditoria_id, a.accion, a.entidad_tipo, a.entidad_id, a.detalles, "
        "a.ip_address, a.fecha, u.username, u.nombre_completo "
        "FROM core.auditoria a LEFT JOIN core.usuario u ON u.usuario_id = a.usuario_id "
        "WHERE 1=1"
    )
    params: list = []
    if accion:
        sql += " AND a.accion = %s"
        params.append(accion)
    if usuario_id:
        sql += " AND a.usuario_id = %s"
        params.append(usuario_id)
    if entidad_tipo:
        sql += " AND a.entidad_tipo = %s"
        params.append(entidad_tipo)
    sql += " ORDER BY a.fecha DESC LIMIT %s"
    params.append(limit)
    return query(sql, tuple(params))


def get_acciones_distintas() -> list[str]:
    rows = query("SELECT DISTINCT accion FROM core.auditoria ORDER BY accion")
    return [r["accion"] for r in rows]
