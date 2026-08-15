"""
Tests del dispatcher de eventos (transform/events.py) — no tocan una
base de datos real: los handlers "log"/"webhook" se parchean o se
reemplaza el registro de acciones por un stub, siguiendo el patrón de
transform/tests/test_json_logic_engine.py.

Ejecutar: python3 -m pytest transform/tests/ -v   (desde la raíz del repo)
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from transform import events


def test_dispatch_events_usa_la_accion_configurada():
    llamadas = []

    @events.action("_test_stub")
    def _stub(evento, accion_config, conn_params):
        llamadas.append((evento, accion_config))

    try:
        triggered = [{"event": "mi_evento", "record": "X-1"}]
        events_config = {"mi_evento": {"action": "_test_stub", "extra": 42}}
        events.dispatch_events(triggered, events_config, "modulo_test", conn_params={})

        assert len(llamadas) == 1
        evento, accion_cfg = llamadas[0]
        assert evento["modulo"] == "modulo_test"
        assert evento["event"] == "mi_evento"
        assert evento["record"] == "X-1"
        assert accion_cfg["extra"] == 42
    finally:
        del events.ACTION_HANDLERS["_test_stub"]


def test_dispatch_events_default_es_log_si_no_esta_configurado():
    with patch("transform.events._persistir_evento") as mock_persist:
        triggered = [{"event": "sin_config", "record": "Y-1"}]
        events.dispatch_events(triggered, events_config={}, module_name="modulo_test", conn_params={})

        mock_persist.assert_called_once()
        evento_arg, accion_arg = mock_persist.call_args.args[0], mock_persist.call_args.args[1]
        assert evento_arg["event"] == "sin_config"
        assert accion_arg == "log"


def test_dispatch_events_handler_que_falla_no_interrumpe_los_demas():
    llamadas = []

    @events.action("_test_falla")
    def _falla(evento, accion_config, conn_params):
        raise RuntimeError("boom")

    @events.action("_test_ok")
    def _ok(evento, accion_config, conn_params):
        llamadas.append(evento)

    try:
        triggered = [
            {"event": "evento_1", "record": "A"},
            {"event": "evento_2", "record": "B"},
        ]
        events_config = {
            "evento_1": {"action": "_test_falla"},
            "evento_2": {"action": "_test_ok"},
        }
        despachados = events.dispatch_events(triggered, events_config, "modulo_test", conn_params={})

        assert len(despachados) == 2  # ambos quedan marcados como despachados aunque uno haya fallado
        assert len(llamadas) == 1
        assert llamadas[0]["event"] == "evento_2"
    finally:
        del events.ACTION_HANDLERS["_test_falla"]
        del events.ACTION_HANDLERS["_test_ok"]


def test_accion_webhook_sin_url_no_falla():
    with patch("transform.events._persistir_evento") as mock_persist:
        events._accion_webhook({"event": "x", "modulo": "m"}, {"action": "webhook"}, conn_params={})
        mock_persist.assert_called_once()
        resultado = mock_persist.call_args.args[2]
        assert "sin URL" in resultado
