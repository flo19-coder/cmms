"""
Tests de auditoria.py — sin Postgres real.

Ejecutar: cd webapp && python3 -m pytest tests/test_auditoria.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auditoria as aud


def test_registrar_evento_llama_execute_con_los_datos_correctos(monkeypatch):
    calls = []
    monkeypatch.setattr(aud, "execute", lambda sql, params: calls.append(params))

    aud.registrar_evento(
        usuario_id=5, accion="LOGIN", entidad_tipo="usuario", entidad_id="jperez",
        detalles={"ok": True}, ip_address="10.0.0.5",
    )

    assert len(calls) == 1
    usuario_id, accion, entidad_tipo, entidad_id, detalles_json, ip = calls[0]
    assert usuario_id == 5
    assert accion == "LOGIN"
    assert entidad_id == "jperez"
    assert ip == "10.0.0.5"
    assert '"ok": true' in detalles_json


def test_registrar_evento_no_lanza_si_falla_la_escritura(monkeypatch):
    def fake_execute(sql, params):
        raise RuntimeError("DB caída")
    monkeypatch.setattr(aud, "execute", fake_execute)

    # NO debe propagar la excepción -- un fallo de auditoría no debe
    # tumbar la operación de negocio que la originó.
    aud.registrar_evento(usuario_id=1, accion="LOGIN")


def test_registrar_evento_sin_detalles_pasa_null(monkeypatch):
    calls = []
    monkeypatch.setattr(aud, "execute", lambda sql, params: calls.append(params))
    aud.registrar_evento(usuario_id=None, accion="LOGIN_FALLIDO", entidad_id="admin")
    assert calls[0][4] is None  # detalles = NULL, no "null" string


def test_registrar_evento_en_cursor_no_hace_commit_propio():
    """
    registrar_evento_en_cursor() NO debe llamar execute()/commit() por su
    cuenta -- tiene que reusar el cursor que le pasan, para que quede
    dentro de la MISMA transacción que la operación que audita.
    """
    class FakeCursor:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params):
            self.executed.append((sql, params))

    cur = FakeCursor()
    aud.registrar_evento_en_cursor(cur, usuario_id=1, accion="CREAR_OT", entidad_id="OT-1")
    assert len(cur.executed) == 1
    assert "INSERT INTO core.auditoria" in cur.executed[0][0]


def test_get_eventos_arma_filtros_correctamente(monkeypatch):
    captured = {}

    def fake_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(aud, "query", fake_query)
    aud.get_eventos(accion="LOGIN", usuario_id=3, entidad_tipo="usuario", limit=50)

    assert "a.accion = %s" in captured["sql"]
    assert "a.usuario_id = %s" in captured["sql"]
    assert "a.entidad_tipo = %s" in captured["sql"]
    assert captured["params"] == ("LOGIN", 3, "usuario", 50)


def test_get_eventos_sin_filtros(monkeypatch):
    captured = {}

    def fake_query(sql, params):
        captured["params"] = params
        return []

    monkeypatch.setattr(aud, "query", fake_query)
    aud.get_eventos()
    assert captured["params"] == (200,)  # solo el LIMIT
