"""
Tests automatizados — corren SIN necesitar Postgres real, usando
monkeypatch sobre las funciones de queries.py/auth.py/db.py. Esto
permite validar la capa HTTP (rutas, auth, roles, códigos de estado,
forma del JSON) en cualquier entorno, incluido CI, sin levantar el
stack completo de Docker.

Ejecutar: cd webapp && python3 -m pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from werkzeug.security import generate_password_hash

FAKE_USERS = {
    "admin": {"usuario_id": 1, "username": "admin", "password_hash": generate_password_hash("admin123"),
               "nombre_completo": "Admin Test", "rol": "ADMIN", "activo": True},
    "supervisor": {"usuario_id": 2, "username": "supervisor", "password_hash": generate_password_hash("super123"),
                    "nombre_completo": "Supervisor Test", "rol": "SUPERVISOR", "activo": True},
    "tecnico": {"usuario_id": 3, "username": "tecnico", "password_hash": generate_password_hash("tecnico123"),
                 "nombre_completo": "Tecnico Test", "rol": "TECNICO", "activo": True},
    "inactivo": {"usuario_id": 4, "username": "inactivo", "password_hash": generate_password_hash("x1234567"),
                  "nombre_completo": "Inactivo Test", "rol": "OPERADOR", "activo": False},
}
FAKE_USERS_BY_ID = {str(u["usuario_id"]): u for u in FAKE_USERS.values()}


def _fake_query_one(sql: str, params: tuple = ()):
    sql_l = sql.lower()
    if "core.usuario" in sql_l and "username" in sql_l:
        user = FAKE_USERS.get(params[0])
        if user and "activo = true" in sql_l and not user["activo"]:
            return None
        return user
    if "core.usuario" in sql_l and "usuario_id" in sql_l:
        return FAKE_USERS_BY_ID.get(str(params[0]))
    return None


@pytest.fixture
def client(monkeypatch):
    fake_activo = {
        "codigo_activo": "EQ-9999", "nombre": "Chiller de prueba",
        "criticidad": "Alta", "fuera_de_servicio": False, "calibracion_vencida": False,
    }

    fakes = {
        "get_dashboard_data": lambda: {
            "kpi": {"ots_en_proceso": 1}, "ots_por_tipo": [], "activos_por_criticidad": [],
            "activos_por_servicio": [], "inspecciones_vencidas": [], "stock_bajo": [], "downtime_total": 0,
        },
        "get_vista_arbol_data": lambda: {"Sede Test": {"Área Test": [fake_activo]}},
        "get_kanban_data": lambda: {"Pendiente": [], "En Proceso": [], "En Revisión": [], "Finalizada": []},
        "get_panel_hoy_data": lambda: {"hoy": "2026-01-01", "ots_hoy": [], "tareas_hoy": []},
        "get_activos_list": lambda **kw: [fake_activo],
    }

    def fake_detalle(codigo):
        from queries import NotFoundError
        if codigo != "EQ-9999":
            raise NotFoundError(codigo)
        return {
            "activo": fake_activo, "ubicacion_path": None, "plan_mantenimiento": None,
            "horas_estimadas": 100, "historial": [], "ultimo_estado": "Sin historial",
            "repuestos_usados": [], "stats": {}, "lecturas": [],
        }
    fakes["get_activo_detalle"] = fake_detalle

    import queries as queries_module
    import api as api_module
    import app as app_module
    import auth as auth_module

    for name, fn in fakes.items():
        monkeypatch.setattr(queries_module, name, fn)
        if hasattr(api_module, name):
            monkeypatch.setattr(api_module, name, fn)
        if hasattr(app_module, name):
            monkeypatch.setattr(app_module, name, fn)

    # auth.py y app.py hacen `from db import query_one/health_check` --
    # cada uno tiene su PROPIA referencia local. Hay que parchear cada
    # módulo importador, no solo `db.query_one` (mismo patrón de bug que
    # ya se encontró y documentó antes con `queries` -- ver README).
    monkeypatch.setattr(auth_module, "query_one", _fake_query_one)
    monkeypatch.setattr(app_module, "health_check", lambda: True)
    monkeypatch.setattr(app_module, "execute", lambda *a, **kw: 1)  # no-op para el UPDATE de ultimo_login
    monkeypatch.setattr(app_module, "query", lambda *a, **kw: list(FAKE_USERS.values()))  # /admin/usuarios

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def login(client, username: str, password: str):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


API_KEY_HEADERS = {"X-API-Key": "cmms-local-dev-key"}


# --- Páginas públicas (flujo QR / kiosco) — sin login ------------------
def test_activo_detalle_publico_sin_login(client):
    assert client.get("/activo/EQ-9999").status_code == 200


def test_activo_detalle_inexistente_404(client):
    assert client.get("/activo/NO-EXISTE").status_code == 404


def test_panel_hoy_publico_sin_login(client):
    assert client.get("/panel/hoy").status_code == 200


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_raiz_redirige_a_dashboard(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


# --- Páginas de gestión: SIN login deben redirigir a /login -----------
@pytest.mark.parametrize("path", ["/dashboard", "/kanban", "/vista-arbol", "/activos", "/admin/usuarios"])
def test_rutas_gestion_sin_login_redirigen(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# --- Login: credenciales -----------------------------------------------
def test_login_correcto_redirige(client):
    resp = login(client, "admin", "admin123")
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]


def test_login_password_incorrecto(client):
    resp = login(client, "admin", "clave-mala")
    assert resp.status_code == 200  # se queda en la página de login
    assert "incorrectos" in resp.get_data(as_text=True).lower()


def test_login_usuario_inexistente(client):
    resp = login(client, "no-existe", "algo123")
    assert resp.status_code == 200


def test_login_usuario_inactivo_rechazado(client):
    resp = login(client, "inactivo", "x1234567")
    assert resp.status_code == 200
    assert "incorrectos" in resp.get_data(as_text=True).lower()


# --- Roles: cada rol ve lo que debe, ni más ni menos -------------------
def test_admin_ve_dashboard_y_admin_usuarios(client):
    login(client, "admin", "admin123")
    assert client.get("/dashboard").status_code == 200
    assert client.get("/admin/usuarios").status_code == 200


def test_supervisor_ve_dashboard_pero_no_admin(client):
    login(client, "supervisor", "super123")
    assert client.get("/dashboard").status_code == 200
    assert client.get("/admin/usuarios").status_code == 403


def test_tecnico_no_ve_dashboard_pero_si_kanban(client):
    login(client, "tecnico", "tecnico123")
    assert client.get("/dashboard").status_code == 403
    assert client.get("/kanban").status_code == 200
    assert client.get("/vista-arbol").status_code == 200


def test_logout_saca_de_sesion(client):
    login(client, "admin", "admin123")
    assert client.get("/dashboard").status_code == 200
    client.get("/logout")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302


# --- API REST: autenticación separada por API key (no por sesión) -----
@pytest.mark.parametrize("path", ["/api/dashboard", "/api/vista-arbol", "/api/kanban", "/api/panel-hoy", "/api/activos"])
def test_api_sin_key_devuelve_401(client, path):
    resp = client.get(path)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "unauthorized"


@pytest.mark.parametrize("path", ["/api/dashboard", "/api/vista-arbol", "/api/kanban", "/api/panel-hoy", "/api/activos"])
def test_api_con_key_devuelve_200(client, path):
    resp = client.get(path, headers=API_KEY_HEADERS)
    assert resp.status_code == 200
    assert resp.is_json


def test_api_activo_detalle_ok(client):
    resp = client.get("/api/activos/EQ-9999", headers=API_KEY_HEADERS)
    assert resp.status_code == 200
    assert resp.get_json()["activo"]["codigo_activo"] == "EQ-9999"


def test_api_activo_detalle_404(client):
    resp = client.get("/api/activos/NO-EXISTE", headers=API_KEY_HEADERS)
    assert resp.status_code == 404


def test_api_activos_filtros_se_pasan(client, monkeypatch):
    captured = {}

    def fake_list(sede=None, servicio=None, criticidad=None):
        captured.update({"sede": sede, "servicio": servicio, "criticidad": criticidad})
        return []
    import api as api_module
    monkeypatch.setattr(api_module, "get_activos_list", fake_list)
    client.get("/api/activos?sede=Sede+Lima&criticidad=Alta", headers=API_KEY_HEADERS)
    assert captured["sede"] == "Sede Lima"
    assert captured["criticidad"] == "Alta"
    assert captured["servicio"] is None
