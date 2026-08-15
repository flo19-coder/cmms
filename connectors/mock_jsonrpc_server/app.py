"""
Servidor JSON-RPC 2.0 de prueba, 100% local — existe para poder
demostrar `connectors/api_connector.py` (protocolo JSON-RPC real) sin
depender de ninguna API paga de terceros. Simula un sistema externo de
mantenimiento que expone tareas vía JSON-RPC.

Implementa la spec (https://www.jsonrpc.org/specification): request
{"jsonrpc":"2.0","method":...,"params":...,"id":...}, response con
"result" o "error" ({"code","message"}), batch requests (lista de
requests -> lista de responses), y notificaciones (sin "id" -> sin
response, salvo en el batch donde igual se omite esa entrada).

Correr: python app.py   (o via docker-compose, servicio mock_jsonrpc)
"""
from __future__ import annotations

from datetime import date, timedelta

from flask import Flask, jsonify, request

app = Flask(__name__)

# Tareas de mantenimiento "externas" — vinculadas a los equipos migrados
# desde el ERP MySQL (AQP-001..AQP-006, ver connectors/mysql_demo_init/),
# para que la demo cuente una historia coherente: un sistema de terceros
# manda tareas para equipos que el CMMS ya conoce.
_ACTIVOS_DEMO = ["AQP-001", "AQP-002", "AQP-003", "AQP-004", "AQP-005", "AQP-006"]
_FRECUENCIAS = ["MENSUAL", "TRIMESTRAL", "SEMESTRAL", "ANUAL"]

DEMO_TAREAS = [
    {
        "id": f"JRPC-{i:03d}",
        "activo_codigo": _ACTIVOS_DEMO[i % len(_ACTIVOS_DEMO)],
        "nombre": f"Inspección externa #{i} — {_ACTIVOS_DEMO[i % len(_ACTIVOS_DEMO)]}",
        "frecuencia": _FRECUENCIAS[i % len(_FRECUENCIAS)],
        "fecha_programada": (date.today() + timedelta(days=i)).isoformat(),
        "estado": "Pendiente",
    }
    for i in range(1, 13)
]

RPC_METHODS = {}


def rpc_method(name: str):
    def deco(fn):
        RPC_METHODS[name] = fn
        return fn
    return deco


@rpc_method("ping")
def _ping(params):
    return "pong"


@rpc_method("tareas.list")
def _tareas_list(params):
    offset = int((params or {}).get("offset", 0))
    limit = int((params or {}).get("limit", 50))
    return {"items": DEMO_TAREAS[offset:offset + limit], "total": len(DEMO_TAREAS)}


def _handle_single(req: dict) -> dict | None:
    req_id = req.get("id") if isinstance(req, dict) else None
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or "method" not in req:
        return {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": req_id}

    method = req["method"]
    params = req.get("params", {})
    is_notification = "id" not in req

    if method not in RPC_METHODS:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": req_id}

    try:
        result = RPC_METHODS[method](params)
    except Exception as e:  # noqa: BLE001 — server JSON-RPC genérico, cualquier excepción se mapea a error -32000
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)}, "id": req_id}

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


@app.route("/", methods=["POST"])
def rpc_endpoint():
    body = request.get_json(force=True, silent=True)
    if body is None:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}), 400

    if isinstance(body, list):
        if not body:
            return jsonify({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": None}), 400
        responses = [r for r in (_handle_single(item) for item in body) if r is not None]
        return jsonify(responses) if responses else ("", 204)

    resp = _handle_single(body)
    return jsonify(resp) if resp is not None else ("", 204)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "methods": list(RPC_METHODS)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5099)
