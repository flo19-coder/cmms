"""
Servicio de dominio para Activos — creación, edición y retiro. Todo
cambio de datos pasa por acá (nunca SQL de negocio directo desde una
ruta de Flask), mismo patrón que `transacciones.py` para Órdenes de
Trabajo (regla global: "Usa servicios transaccionales; no escribas SQL
de negocio directamente desde rutas").

Especificación: ESPECIFICACION_CMMS_CODEX_2.md, "Entrega 1: creación de
activos".
"""
from __future__ import annotations

import re

from db import query_one, transaction
from auditoria import registrar_evento_en_cursor


class BusinessRuleError(Exception):
    """La operación viola una regla de negocio (ej. código duplicado, estado inválido)."""


ESTADOS_VALIDOS = ("OPERATIVO", "FUERA_DE_SERVICIO", "RETIRADO")
CRITICIDADES_VALIDAS = ("Muy Alta", "Alta", "Media", "Baja")

CAMPOS_FORMULARIO = (
    "codigo_activo", "nombre", "tipo_equipo", "fabricante", "modelo", "numero_serie",
    "nivel_2_sede", "nivel_3_servicio", "ubicacion_path", "criticidad",
    "horas_uso_promedio_diario", "plan_mantenimiento", "fecha_instalacion",
    "estado", "notas",
)


def normalizar_codigo(valor: str | None) -> str:
    """Trim + colapsa espacios internos múltiples a uno solo, mayúsculas.
    Se usa tanto para `codigo_activo` como para `numero_serie`."""
    return re.sub(r"\s+", " ", (valor or "").strip()).upper()


def _validar(datos: dict) -> None:
    faltantes = [c for c in ("codigo_activo", "nombre", "tipo_equipo") if not (datos.get(c) or "").strip()]
    if faltantes:
        raise BusinessRuleError(f"Campos obligatorios faltantes: {', '.join(faltantes)}.")

    estado = datos.get("estado") or "OPERATIVO"
    if estado not in ESTADOS_VALIDOS:
        raise BusinessRuleError(f"Estado inválido: '{estado}'.")

    criticidad = datos.get("criticidad")
    if criticidad and criticidad not in CRITICIDADES_VALIDAS:
        raise BusinessRuleError(f"Criticidad inválida: '{criticidad}'.")

    horas = datos.get("horas_uso_promedio_diario")
    if horas not in (None, ""):
        try:
            if not (0 <= float(horas) <= 24):
                raise BusinessRuleError("Las horas de uso promedio diario deben estar entre 0 y 24.")
        except (TypeError, ValueError):
            raise BusinessRuleError("Las horas de uso promedio diario deben ser un número.")


def _valores_fila(datos: dict) -> dict:
    estado = datos.get("estado") or "OPERATIVO"
    return {
        "nombre": datos["nombre"].strip(),
        "tipo_equipo": datos["tipo_equipo"].strip(),
        "fabricante": (datos.get("fabricante") or "").strip() or None,
        "modelo": (datos.get("modelo") or "").strip() or None,
        "numero_serie": normalizar_codigo(datos.get("numero_serie")) or None,
        "nivel_2_sede": (datos.get("nivel_2_sede") or "").strip() or None,
        "nivel_3_servicio": (datos.get("nivel_3_servicio") or "").strip() or None,
        "ubicacion_path": (datos.get("ubicacion_path") or "").strip() or None,
        "criticidad": datos.get("criticidad") or None,
        "horas_uso_promedio_diario": float(datos["horas_uso_promedio_diario"]) if datos.get("horas_uso_promedio_diario") not in (None, "") else None,
        "plan_mantenimiento": (datos.get("plan_mantenimiento") or "").strip() or None,
        "fecha_instalacion": datos.get("fecha_instalacion") or None,
        "estado": estado,
        "notas": (datos.get("notas") or "").strip() or None,
        # Compatibilidad con las pantallas/consultas actuales, que ya
        # filtran por estos 2 booleanos (dashboard, vista árbol, etc.)
        # -- se derivan del estado nuevo, nunca al revés.
        "habilitado": estado != "RETIRADO",
        "fuera_de_servicio": estado == "FUERA_DE_SERVICIO",
    }


def crear_activo(datos: dict, usuario_id: int, ip_address: str | None = None) -> str:
    _validar(datos)
    codigo = normalizar_codigo(datos.get("codigo_activo"))
    if not codigo:
        raise BusinessRuleError("El código del activo es obligatorio.")

    if query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,)):
        raise BusinessRuleError(f"Ya existe un activo con el código '{codigo}'.")

    valores = _valores_fila(datos)

    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO core.activo (
                codigo_activo, nombre, tipo_equipo, fabricante, modelo, numero_serie,
                nivel_2_sede, nivel_3_servicio, ubicacion_path, criticidad,
                horas_uso_promedio_diario, plan_mantenimiento, fecha_instalacion,
                estado, notas, habilitado, fuera_de_servicio
            ) VALUES (
                %(codigo)s, %(nombre)s, %(tipo_equipo)s, %(fabricante)s, %(modelo)s, %(numero_serie)s,
                %(nivel_2_sede)s, %(nivel_3_servicio)s, %(ubicacion_path)s, %(criticidad)s,
                %(horas_uso_promedio_diario)s, %(plan_mantenimiento)s, %(fecha_instalacion)s,
                %(estado)s, %(notas)s, %(habilitado)s, %(fuera_de_servicio)s
            )
            """,
            {**valores, "codigo": codigo},
        )
        registrar_evento_en_cursor(
            cur, usuario_id=usuario_id, accion="CREAR_ACTIVO", entidad_tipo="activo",
            entidad_id=codigo, detalles={"nombre": valores["nombre"], "estado": valores["estado"]},
            ip_address=ip_address,
        )
    return codigo


def editar_activo(codigo: str, datos: dict, usuario_id: int, ip_address: str | None = None) -> None:
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        raise BusinessRuleError(f"El activo '{codigo}' no existe.")

    # El código autoritativo de un activo existente es el de la URL
    # (parámetro `codigo`), nunca lo que venga en el body del form --
    # así una llamada que no lo reenvíe (o que intente mandar uno
    # distinto) igual valida y actualiza el activo correcto.
    datos = {**datos, "codigo_activo": codigo}

    _validar(datos)
    valores = _valores_fila(datos)

    with transaction() as cur:
        cur.execute(
            """
            UPDATE core.activo SET
                nombre = %(nombre)s, tipo_equipo = %(tipo_equipo)s, fabricante = %(fabricante)s,
                modelo = %(modelo)s, numero_serie = %(numero_serie)s,
                nivel_2_sede = %(nivel_2_sede)s, nivel_3_servicio = %(nivel_3_servicio)s,
                ubicacion_path = %(ubicacion_path)s, criticidad = %(criticidad)s,
                horas_uso_promedio_diario = %(horas_uso_promedio_diario)s,
                plan_mantenimiento = %(plan_mantenimiento)s, fecha_instalacion = %(fecha_instalacion)s,
                estado = %(estado)s, notas = %(notas)s,
                habilitado = %(habilitado)s, fuera_de_servicio = %(fuera_de_servicio)s,
                updated_at = now()
            WHERE codigo_activo = %(codigo)s
            """,
            {**valores, "codigo": codigo},
        )
        registrar_evento_en_cursor(
            cur, usuario_id=usuario_id, accion="EDITAR_ACTIVO", entidad_tipo="activo",
            entidad_id=codigo, detalles={"estado": valores["estado"]}, ip_address=ip_address,
        )


def retirar_activo(codigo: str, motivo: str, usuario_id: int, ip_address: str | None = None) -> None:
    """
    Retirar = transición de estado a RETIRADO, NUNCA un DELETE. Conserva
    OTs, lecturas, fotos y documentos -- este servicio no borra ninguna
    fila de ninguna otra tabla. Bloquea nueva programación porque las
    consultas de "activos disponibles" ya filtran por habilitado/estado
    (ver queries.py) -- acá solo se cambia el estado con auditoría.
    """
    if not (motivo or "").strip():
        raise BusinessRuleError("Retirar un activo requiere un motivo.")
    activo = query_one("SELECT codigo_activo, estado FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        raise BusinessRuleError(f"El activo '{codigo}' no existe.")
    if activo["estado"] == "RETIRADO":
        raise BusinessRuleError(f"El activo '{codigo}' ya está retirado.")

    with transaction() as cur:
        cur.execute(
            "UPDATE core.activo SET estado = 'RETIRADO', habilitado = FALSE, updated_at = now() "
            "WHERE codigo_activo = %s",
            (codigo,),
        )
        registrar_evento_en_cursor(
            cur, usuario_id=usuario_id, accion="RETIRAR_ACTIVO", entidad_tipo="activo",
            entidad_id=codigo, detalles={"motivo": motivo.strip()}, ip_address=ip_address,
        )
