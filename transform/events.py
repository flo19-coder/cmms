"""
Sistema de eventos dinámico (el "Automatizador" del motor ETL, en el
mismo espíritu del módulo Automatizador de Fracttal — ver manual, pág.
202+). `postgres_loader.load_module()` ya evalúa `event_rules` (reglas
JSON Logic) de cada config y arma la lista `triggered_events`; este
módulo es el que las DISPARA de verdad — antes solo se logueaban.

Cada evento disparado queda registrado en `core.evento_automatizacion`
(igual espíritu que `core.auditoria`, pero para eventos de datos, no de
usuarios) y opcionalmente ejecuta una acción configurable por evento
(bloque "events" del config del módulo, ej. transform/config/
equipos_sede_externa.json):

    "event_rules": {"equipo_critico_nuevo": {"==": [{"var": "criticidad"}, "Muy Alta"]}},
    "events": {"equipo_critico_nuevo": {"action": "log"}}

Registro de acciones extensible (@action) — hoy soporta:
  log      — solo persiste el evento (default si no se configura acción)
  webhook  — además hace POST del evento como JSON a una URL configurada
             ("url" o "url_env_var" en el bloque de la acción)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger("cmms.events")

ACTION_HANDLERS: dict[str, Callable] = {}


def action(name: str):
    def deco(fn: Callable):
        ACTION_HANDLERS[name] = fn
        return fn
    return deco


def _persistir_evento(evento: dict, accion: str, resultado: str, conn_params: dict) -> None:
    import psycopg2

    conn = psycopg2.connect(**conn_params)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO core.evento_automatizacion
                    (modulo, evento_nombre, record_key, accion, resultado, detalles)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    evento.get("modulo"),
                    evento.get("event"),
                    str(evento.get("record")) if evento.get("record") is not None else None,
                    accion,
                    resultado,
                    json.dumps(evento, default=str),
                ),
            )
        conn.commit()
    finally:
        conn.close()


@action("log")
def _accion_log(evento: dict, accion_config: dict, conn_params: dict) -> None:
    logger.info("Evento disparado: %s", evento)
    _persistir_evento(evento, "log", "registrado", conn_params)


@action("webhook")
def _accion_webhook(evento: dict, accion_config: dict, conn_params: dict) -> None:
    import os
    import requests

    url = accion_config.get("url") or os.environ.get(accion_config.get("url_env_var", ""), "")
    if not url:
        _persistir_evento(evento, "webhook", "error: sin URL configurada", conn_params)
        return
    try:
        resp = requests.post(url, json=evento, timeout=10)
        resp.raise_for_status()
        _persistir_evento(evento, "webhook", f"ok: {resp.status_code}", conn_params)
    except Exception as e:  # noqa: BLE001 — un webhook que falla no debe tumbar el pipeline
        logger.warning("Webhook de evento falló (%s): %s", evento.get("event"), e)
        _persistir_evento(evento, "webhook", f"error: {e}", conn_params)


def dispatch_events(
    triggered_events: list[dict], events_config: dict, module_name: str, conn_params: dict
) -> list[dict]:
    """
    triggered_events: lo que devuelve postgres_loader.load_module() en
    summary["eventos"] — [{"event": "nombre_evento", "record": clave}, ...]
    events_config: el bloque "events" del config del módulo (event_name -> {"action": ...})
    """
    despachados = []
    for evento_raw in triggered_events:
        evento = dict(evento_raw, modulo=module_name)
        accion_cfg = events_config.get(evento["event"], {"action": "log"})
        nombre_accion = accion_cfg.get("action", "log")
        handler = ACTION_HANDLERS.get(nombre_accion, ACTION_HANDLERS["log"])
        try:
            handler(evento, accion_cfg, conn_params)
        except Exception:
            logger.exception("Fallo despachando evento %s (acción=%s)", evento["event"], nombre_accion)
        despachados.append(evento)
    return despachados
