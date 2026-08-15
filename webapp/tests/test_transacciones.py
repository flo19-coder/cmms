"""
Tests de transacciones.py — validan la máquina de estados y las reglas
de negocio SIN tocar Postgres real (se simula `db.transaction()` con un
cursor falso que registra qué SQL se ejecutó).

Ejecutar: cd webapp && python3 -m pytest tests/test_transacciones.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from contextlib import contextmanager

import transacciones as tx


class FakeCursor:
    """Registra cada .execute() para poder inspeccionar qué se intentó hacer."""
    def __init__(self, fetchone_responses=None):
        self.calls = []
        self._fetchone_responses = list(fetchone_responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql.strip().split()[0].upper(), sql, params))

    def fetchone(self):
        if self._fetchone_responses:
            return self._fetchone_responses.pop(0)
        return None


@pytest.fixture
def fake_transaction(monkeypatch):
    """Reemplaza db.transaction() por un context manager que da un FakeCursor."""
    cursor_holder = {}

    def make_transaction(fetchone_responses=None):
        @contextmanager
        def _tx():
            cur = FakeCursor(fetchone_responses)
            cursor_holder["cur"] = cur
            yield cur
        return _tx

    monkeypatch.setattr(tx, "transaction", make_transaction())
    return cursor_holder


def test_crear_ot_rechaza_tipo_invalido(monkeypatch):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: {"codigo_activo": "EQ-0001"})
    with pytest.raises(tx.BusinessRuleError):
        tx.crear_orden_trabajo(
            activo_codigo="EQ-0001", tipo_ot="INVALIDO", descripcion_tarea="x",
            prioridad="Alta", fecha_programada="2026-01-01", responsable_nombre=None,
            clasificacion_1=None, usuario_id=1,
        )


def test_crear_ot_rechaza_activo_inexistente(monkeypatch):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: None)
    with pytest.raises(tx.BusinessRuleError, match="no existe"):
        tx.crear_orden_trabajo(
            activo_codigo="NO-EXISTE", tipo_ot="CORRECTIVO", descripcion_tarea="x",
            prioridad="Alta", fecha_programada="2026-01-01", responsable_nombre=None,
            clasificacion_1=None, usuario_id=1,
        )


def test_crear_ot_ok_inserta_y_registra_historial(monkeypatch, fake_transaction):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: {"codigo_activo": "EQ-0001"})
    resultado = tx.crear_orden_trabajo(
        activo_codigo="EQ-0001", tipo_ot="CORRECTIVO", descripcion_tarea="x",
        prioridad="Alta", fecha_programada="2026-01-01", responsable_nombre=None,
        clasificacion_1=None, usuario_id=1,
    )
    assert resultado["estado"] == "Pendiente"
    cur = fake_transaction["cur"]
    kinds = [c[0] for c in cur.calls]
    assert kinds == ["INSERT", "INSERT", "INSERT"]  # 1) la OT, 2) el historial, 3) la auditoría


# --- Máquina de estados -------------------------------------------------
@pytest.mark.parametrize("estado_actual,nuevo_estado,valido", [
    ("Pendiente", "En Proceso", True),
    ("Pendiente", "Finalizada", False),      # no se puede saltar directo
    ("En Proceso", "En Revisión", True),
    ("En Proceso", "Finalizada", False),      # tiene que pasar por revisión
    ("En Revisión", "Finalizada", True),
    ("En Revisión", "Pendiente", False),      # no retrocede hasta el inicio
    ("Finalizada", "En Proceso", False),      # estado terminal
    ("Cancelada", "Pendiente", False),        # estado terminal
])
def test_transiciones_maquina_estados(monkeypatch, fake_transaction, estado_actual, nuevo_estado, valido):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: {"ot_id": "OT-1", "estado": estado_actual})
    if valido:
        resultado = tx.cambiar_estado_ot(ot_id="OT-1", nuevo_estado=nuevo_estado, usuario_id=1)
        assert resultado["estado_nuevo"] == nuevo_estado
    else:
        with pytest.raises(tx.InvalidTransitionError):
            tx.cambiar_estado_ot(ot_id="OT-1", nuevo_estado=nuevo_estado, usuario_id=1)


def test_cambiar_estado_ot_inexistente(monkeypatch):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: None)
    with pytest.raises(tx.BusinessRuleError, match="no existe"):
        tx.cambiar_estado_ot(ot_id="OT-FANTASMA", nuevo_estado="En Proceso", usuario_id=1)


# --- Finalizar con repuestos: la parte "transaccional" de verdad -------
def test_finalizar_ot_rechaza_si_no_esta_en_revision(monkeypatch):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: {"ot_id": "OT-1", "estado": "Pendiente"})
    with pytest.raises(tx.InvalidTransitionError):
        tx.finalizar_ot(ot_id="OT-1", usuario_id=1, repuestos=[])


def _fake_query_one_sin_checklist(sql, params=()):
    # La OT existe y está En Revisión; cualquier consulta a
    # core.activo/core.checklist_template devuelve None -> el activo
    # no tiene checklist definido, finalizar_ot sigue sin exigir ítems.
    if "core.orden_trabajo" in sql:
        return {"ot_id": "OT-1", "activo_codigo": "EQ-0001", "estado": "En Revisión"}
    return None


def test_finalizar_ot_sin_repuestos_ok(monkeypatch, fake_transaction):
    monkeypatch.setattr(tx, "query_one", _fake_query_one_sin_checklist)
    resultado = tx.finalizar_ot(ot_id="OT-1", usuario_id=1, repuestos=[])
    assert resultado["estado"] == "Finalizada"
    assert resultado["repuestos_registrados"] == 0


def test_finalizar_ot_stock_insuficiente_lanza_error(monkeypatch):
    monkeypatch.setattr(tx, "query_one", _fake_query_one_sin_checklist)

    # SELECT ... FOR UPDATE devuelve stock=1, pero se piden 5
    @contextmanager
    def fake_tx():
        cur = FakeCursor(fetchone_responses=[{"stock_actual": 1}])
        yield cur
    monkeypatch.setattr(tx, "transaction", fake_tx)

    with pytest.raises(tx.BusinessRuleError, match="Stock insuficiente"):
        tx.finalizar_ot(
            ot_id="OT-1", usuario_id=1,
            repuestos=[{"codigo_repuesto": "REP-001", "cantidad": 5}],
        )


def test_finalizar_ot_repuesto_inexistente_lanza_error(monkeypatch):
    monkeypatch.setattr(tx, "query_one", _fake_query_one_sin_checklist)

    @contextmanager
    def fake_tx():
        cur = FakeCursor(fetchone_responses=[None])  # el repuesto no existe
        yield cur
    monkeypatch.setattr(tx, "transaction", fake_tx)

    with pytest.raises(tx.BusinessRuleError, match="no existe"):
        tx.finalizar_ot(
            ot_id="OT-1", usuario_id=1,
            repuestos=[{"codigo_repuesto": "REP-FANTASMA", "cantidad": 1}],
        )


def test_finalizar_ot_con_repuestos_suficientes_descuenta_stock(monkeypatch):
    monkeypatch.setattr(tx, "query_one", _fake_query_one_sin_checklist)

    @contextmanager
    def fake_tx():
        cur = FakeCursor(fetchone_responses=[{"stock_actual": 10}])
        yield cur
    monkeypatch.setattr(tx, "transaction", fake_tx)

    resultado = tx.finalizar_ot(
        ot_id="OT-1", usuario_id=1,
        repuestos=[{"codigo_repuesto": "REP-001", "cantidad": 3}],
    )
    assert resultado["repuestos_registrados"] == 1


# --- Checklist de mantenimiento -----------------------------------------
def test_get_checklist_sin_plantilla_devuelve_none(monkeypatch):
    def fake_query_one(sql, params=()):
        if "core.activo" in sql:
            return {"tipo_equipo": "Bomba de Agua"}
        if "core.checklist_template" in sql:
            return None  # no hay plantilla para ese tipo
        return None
    monkeypatch.setattr(tx, "query_one", fake_query_one)
    assert tx.get_checklist_para_activo("EQ-9999") is None


def test_get_checklist_activo_inexistente_devuelve_none(monkeypatch):
    monkeypatch.setattr(tx, "query_one", lambda *a, **kw: None)
    assert tx.get_checklist_para_activo("NO-EXISTE") is None


def test_finalizar_ot_con_checklist_obligatorio_incompleto_rechaza(monkeypatch):
    def fake_query_one(sql, params=()):
        if "core.orden_trabajo" in sql:
            return {"ot_id": "OT-1", "activo_codigo": "EQ-0002", "estado": "En Revisión"}
        if "core.activo" in sql:
            return {"tipo_equipo": "Generador Eléctrico de Emergencia"}
        if "core.checklist_template" in sql and "item" not in sql:
            return {"checklist_template_id": 1, "nombre": "Preventivo Generador", "tipo_equipo": "Generador Eléctrico de Emergencia"}
        return None

    def fake_query(sql, params=()):
        if "checklist_template_item" in sql:
            return [
                {"item_id": 1, "orden": 1, "descripcion": "Nivel de aceite", "tipo_respuesta": "boolean", "obligatorio": True},
                {"item_id": 2, "orden": 2, "descripcion": "Voltaje batería", "tipo_respuesta": "numero", "obligatorio": True},
            ]
        return []

    monkeypatch.setattr(tx, "query_one", fake_query_one)
    monkeypatch.setattr(tx, "query", fake_query)

    # Solo contesta el ítem 1, falta el 2 (obligatorio) -> debe rechazar
    with pytest.raises(tx.BusinessRuleError, match="Voltaje batería"):
        tx.finalizar_ot(ot_id="OT-1", usuario_id=1, checklist_respuestas=[{"item_id": 1, "ok": True}])


def test_finalizar_ot_con_checklist_completo_ok(monkeypatch):
    def fake_query_one(sql, params=()):
        if "core.orden_trabajo" in sql:
            return {"ot_id": "OT-1", "activo_codigo": "EQ-0002", "estado": "En Revisión"}
        if "core.activo" in sql:
            return {"tipo_equipo": "Generador Eléctrico de Emergencia"}
        if "core.checklist_template" in sql and "item" not in sql:
            return {"checklist_template_id": 1, "nombre": "Preventivo Generador", "tipo_equipo": "Generador Eléctrico de Emergencia"}
        return None

    def fake_query(sql, params=()):
        if "checklist_template_item" in sql:
            return [{"item_id": 1, "orden": 1, "descripcion": "Nivel de aceite", "tipo_respuesta": "boolean", "obligatorio": True}]
        return []

    monkeypatch.setattr(tx, "query_one", fake_query_one)
    monkeypatch.setattr(tx, "query", fake_query)

    @contextmanager
    def fake_tx():
        yield FakeCursor()
    monkeypatch.setattr(tx, "transaction", fake_tx)

    resultado = tx.finalizar_ot(ot_id="OT-1", usuario_id=1, checklist_respuestas=[{"item_id": 1, "ok": True}])
    assert resultado["estado"] == "Finalizada"
