"""
API REST del CMMS — pensada para que una interfaz más rica (React, app
móvil de los técnicos, integraciones externas) consuma los mismos datos
que hoy se ven en HTML, sin tener que parsear páginas.

Autenticación: header `X-API-Key`, comparado contra la variable de
entorno CMMS_API_KEY. Es deliberadamente simple (no OAuth2/JWT) porque
esto corre en la red interna de la clínica, en un servidor local — no
expuesto a internet. Si más adelante esto se expone fuera de la red
local, hay que reemplazar esto por autenticación real (ver README).

Las páginas HTML (app.py) NO pasan por esta autenticación — son de
lectura para el kiosco/QR y deben poder abrirse sin fricción desde
cualquier celular en la red de la clínica.
"""
from __future__ import annotations

import os
from functools import wraps

from flask import Blueprint, jsonify, request

from queries import (
    get_dashboard_data, get_vista_arbol_data, get_kanban_data,
    get_panel_hoy_data, get_activos_list, get_activo_detalle, NotFoundError,
)

api_bp = Blueprint("api", __name__)

API_KEY = os.environ.get("CMMS_API_KEY", "cmms-local-dev-key")


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-API-Key")
        if provided != API_KEY:
            return jsonify({"error": "unauthorized", "message": "Header X-API-Key inválido o ausente."}), 401
        return fn(*args, **kwargs)
    return wrapper


@api_bp.route("/dashboard")
@require_api_key
def api_dashboard():
    return jsonify(get_dashboard_data())


@api_bp.route("/vista-arbol")
@require_api_key
def api_vista_arbol():
    return jsonify(get_vista_arbol_data())


@api_bp.route("/kanban")
@require_api_key
def api_kanban():
    return jsonify(get_kanban_data())


@api_bp.route("/panel-hoy")
@require_api_key
def api_panel_hoy():
    return jsonify(get_panel_hoy_data())


@api_bp.route("/activos")
@require_api_key
def api_activos():
    activos = get_activos_list(
        sede=request.args.get("sede"),
        servicio=request.args.get("servicio"),
        criticidad=request.args.get("criticidad"),
    )
    return jsonify({"count": len(activos), "results": activos})


@api_bp.route("/activos/<codigo>")
@require_api_key
def api_activo_detalle(codigo):
    try:
        data = get_activo_detalle(codigo)
    except NotFoundError:
        return jsonify({"error": "not_found", "message": f"Activo '{codigo}' no existe."}), 404
    return jsonify(data)
