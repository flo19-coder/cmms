"""
Entrega 1 (ESPECIFICACION_CMMS_CODEX_2.md): pruebas de integración del
servicio de dominio de activos (webapp/activos_servicio.py) contra
Postgres real -- creación, edición, retiro, unicidad de código,
normalización de espacios, transaccionalidad y auditoría.

Requiere Postgres real vía CMMS_DW_*. Se salta automáticamente si no
hay conexión disponible (mismo patrón que
scripts/tests/test_bootstrap_alembic_integration.py).

Ejecutar: cd webapp && python3 -m pytest tests/test_activos_servicio.py -v
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import pytest

from db import DB_PARAMS, execute, query, query_one
import activos_servicio as svc


def _postgres_disponible() -> bool:
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_disponible(), reason="requiere Postgres real vía CMMS_DW_*")


def _usuario_admin_id() -> int:
    row = query_one("SELECT usuario_id FROM core.usuario WHERE username = 'admin' LIMIT 1")
    if not row:
        pytest.skip("requiere el usuario demo 'admin' (scripts/seed_demo_users.py)")
    return row["usuario_id"]


def _fila_activo(codigo: str) -> dict | None:
    return query_one("SELECT * FROM core.activo WHERE codigo_activo = %s", (codigo,))


def _eventos_auditoria(codigo: str) -> list[dict]:
    return query(
        "SELECT accion, detalles FROM core.auditoria WHERE entidad_tipo = 'activo' AND entidad_id = %s ORDER BY fecha",
        (codigo,),
    )


@pytest.fixture
def codigo_prueba():
    codigo = f"TEST-{uuid.uuid4().hex[:8].upper()}"
    yield codigo
    execute("DELETE FROM core.auditoria WHERE entidad_tipo = 'activo' AND entidad_id = %s", (codigo,))
    execute("DELETE FROM core.activo WHERE codigo_activo = %s", (codigo,))


def test_normalizar_codigo_colapsa_espacios_y_mayuscula():
    assert svc.normalizar_codigo("  eq   0099  ") == "EQ 0099"
    assert svc.normalizar_codigo(None) == ""


def test_crear_activo_exitoso_queda_en_bd_y_auditado(codigo_prueba):
    usuario_id = _usuario_admin_id()
    codigo = svc.crear_activo(
        {
            "codigo_activo": f"  {codigo_prueba}  ",  # espacios de sobra -- debe normalizarse
            "nombre": "Chiller de prueba", "tipo_equipo": "Chiller",
            "nivel_2_sede": "Sede Test", "criticidad": "Alta",
        },
        usuario_id=usuario_id, ip_address="127.0.0.1",
    )
    assert codigo == codigo_prueba

    fila = _fila_activo(codigo_prueba)
    assert fila is not None
    assert fila["nombre"] == "Chiller de prueba"
    assert fila["estado"] == "OPERATIVO"
    assert fila["habilitado"] is True
    assert fila["fuera_de_servicio"] is False

    eventos = _eventos_auditoria(codigo_prueba)
    assert any(e["accion"] == "CREAR_ACTIVO" for e in eventos)


def test_crear_activo_codigo_duplicado_falla(codigo_prueba):
    usuario_id = _usuario_admin_id()
    datos = {"codigo_activo": codigo_prueba, "nombre": "A", "tipo_equipo": "T"}
    svc.crear_activo(datos, usuario_id=usuario_id)
    with pytest.raises(svc.BusinessRuleError, match="Ya existe"):
        svc.crear_activo(datos, usuario_id=usuario_id)
    # confirma que no quedó un segundo intento a medias
    assert len(query("SELECT 1 FROM core.activo WHERE codigo_activo = %s", (codigo_prueba,))) == 1


def test_crear_activo_campos_obligatorios_faltantes():
    with pytest.raises(svc.BusinessRuleError, match="obligatorios"):
        svc.crear_activo({"codigo_activo": "X-SIN-NOMBRE"}, usuario_id=1)


def test_crear_activo_estado_invalido_falla(codigo_prueba):
    with pytest.raises(svc.BusinessRuleError, match="Estado inválido"):
        svc.crear_activo(
            {"codigo_activo": codigo_prueba, "nombre": "N", "tipo_equipo": "T", "estado": "INVENTADO"},
            usuario_id=1,
        )


def test_editar_activo_actualiza_y_audita(codigo_prueba):
    usuario_id = _usuario_admin_id()
    svc.crear_activo({"codigo_activo": codigo_prueba, "nombre": "Original", "tipo_equipo": "T"}, usuario_id=usuario_id)

    svc.editar_activo(
        codigo_prueba,
        {"codigo_activo": codigo_prueba, "nombre": "Editado", "tipo_equipo": "T2", "numero_serie": "  sn 001  "},
        usuario_id=usuario_id,
    )

    fila = _fila_activo(codigo_prueba)
    assert fila["nombre"] == "Editado"
    assert fila["tipo_equipo"] == "T2"
    assert fila["numero_serie"] == "SN 001"

    eventos = _eventos_auditoria(codigo_prueba)
    assert any(e["accion"] == "EDITAR_ACTIVO" for e in eventos)


def test_editar_activo_sin_codigo_en_el_body_funciona_igual(codigo_prueba):
    """
    Regresión: el código autoritativo de una edición es el de la URL
    (parámetro `codigo`), no lo que venga en el body del formulario --
    un caller que no reenvíe `codigo_activo` en `datos` (ej. un cliente
    API, o un test) igual debe poder editar el activo correcto.
    """
    usuario_id = _usuario_admin_id()
    svc.crear_activo({"codigo_activo": codigo_prueba, "nombre": "Original", "tipo_equipo": "T"}, usuario_id=usuario_id)

    svc.editar_activo(codigo_prueba, {"nombre": "Editado sin código en el body", "tipo_equipo": "T2"}, usuario_id=usuario_id)

    fila = _fila_activo(codigo_prueba)
    assert fila["nombre"] == "Editado sin código en el body"


def test_editar_activo_inexistente_falla():
    with pytest.raises(svc.BusinessRuleError, match="no existe"):
        svc.editar_activo("NO-EXISTE-XYZ-000", {"nombre": "x", "tipo_equipo": "y"}, usuario_id=1)


def test_retirar_activo_cambia_estado_y_conserva_habilitado_en_false(codigo_prueba):
    usuario_id = _usuario_admin_id()
    svc.crear_activo({"codigo_activo": codigo_prueba, "nombre": "N", "tipo_equipo": "T"}, usuario_id=usuario_id)

    svc.retirar_activo(codigo_prueba, motivo="Reemplazado por equipo nuevo", usuario_id=usuario_id)

    fila = _fila_activo(codigo_prueba)
    assert fila["estado"] == "RETIRADO"
    assert fila["habilitado"] is False

    eventos = _eventos_auditoria(codigo_prueba)
    evento_retiro = next(e for e in eventos if e["accion"] == "RETIRAR_ACTIVO")
    assert evento_retiro["detalles"]["motivo"] == "Reemplazado por equipo nuevo"


def test_retirar_activo_sin_motivo_falla(codigo_prueba):
    usuario_id = _usuario_admin_id()
    svc.crear_activo({"codigo_activo": codigo_prueba, "nombre": "N", "tipo_equipo": "T"}, usuario_id=usuario_id)
    with pytest.raises(svc.BusinessRuleError, match="motivo"):
        svc.retirar_activo(codigo_prueba, motivo="", usuario_id=usuario_id)


def test_retirar_activo_dos_veces_falla(codigo_prueba):
    usuario_id = _usuario_admin_id()
    svc.crear_activo({"codigo_activo": codigo_prueba, "nombre": "N", "tipo_equipo": "T"}, usuario_id=usuario_id)
    svc.retirar_activo(codigo_prueba, motivo="Motivo 1", usuario_id=usuario_id)
    with pytest.raises(svc.BusinessRuleError, match="ya está retirado"):
        svc.retirar_activo(codigo_prueba, motivo="Motivo 2", usuario_id=usuario_id)


def test_retirar_activo_conserva_historial_de_otras_tablas(codigo_prueba):
    """
    'Retirar un activo debe conservar OTs, lecturas, fotos y documentos'
    -- este servicio nunca hace DELETE sobre ninguna otra tabla, solo
    UPDATE del estado del propio activo. Lo demostramos insertando una
    OT asociada y confirmando que sigue ahí después de retirar.
    """
    usuario_id = _usuario_admin_id()
    svc.crear_activo({"codigo_activo": codigo_prueba, "nombre": "N", "tipo_equipo": "T"}, usuario_id=usuario_id)

    ot_id = f"OT-TEST-{uuid.uuid4().hex[:6].upper()}"
    execute(
        "INSERT INTO core.orden_trabajo (ot_id, activo_codigo, tipo_ot, estado, fecha_programada, prioridad) "
        "VALUES (%s, %s, 'CORRECTIVO', 'Pendiente', CURRENT_DATE, 'Media')",
        (ot_id, codigo_prueba),
    )
    try:
        svc.retirar_activo(codigo_prueba, motivo="Retiro de prueba", usuario_id=usuario_id)
        assert query_one("SELECT ot_id FROM core.orden_trabajo WHERE ot_id = %s", (ot_id,)) is not None
    finally:
        execute("DELETE FROM core.orden_trabajo WHERE ot_id = %s", (ot_id,))
