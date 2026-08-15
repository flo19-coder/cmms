"""
Autenticación (sesión de usuario) y control de acceso por rol.

Diseño deliberado sobre QUÉ queda detrás de login y qué no:

- /panel/hoy y /activo/<codigo> quedan PÚBLICOS (sin login). Son el flujo
  físico real: un operador escanea el QR de un equipo en la pared del
  cuarto de máquinas, o alguien deja el panel de kiosco abierto en una
  pantalla. Pedir login ahí rompe ese flujo.
- /dashboard, /kanban, /vista-arbol, /activos (listado) y /admin/*
  quedan detrás de login, porque son vistas de gestión, no de piso.

Esto es una decisión de producto, no un descuido — está documentada acá
y en el README para que se pueda revisar/cambiar a propósito.
"""
from __future__ import annotations

import logging
from functools import wraps

from flask import redirect, url_for, request, abort, flash
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import check_password_hash

from db import query_one

logger = logging.getLogger("cmms.auth")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar."
login_manager.login_message_category = "info"

ROLES_JERARQUIA = ["OPERADOR", "TECNICO", "SUPERVISOR", "ADMIN"]


class User(UserMixin):
    def __init__(self, row: dict):
        self.id = str(row["usuario_id"])
        self.username = row["username"]
        self.nombre_completo = row["nombre_completo"]
        self.rol = row["rol"]
        self.activo = row["activo"]

    @property
    def is_active(self) -> bool:  # sobreescribe UserMixin.is_active
        return self.activo

    def tiene_rol(self, *roles_permitidos: str) -> bool:
        return self.rol in roles_permitidos


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    row = query_one("SELECT * FROM core.usuario WHERE usuario_id = %s", (user_id,))
    return User(row) if row else None


def authenticate(username: str, password: str) -> User | None:
    row = query_one("SELECT * FROM core.usuario WHERE username = %s AND activo = TRUE", (username,))
    if not row:
        logger.info("Login fallido (usuario no existe o inactivo): %s", username)
        return None
    if not check_password_hash(row["password_hash"], password):
        logger.info("Login fallido (password incorrecto): %s", username)
        return None
    return User(row)


def role_required(*roles_permitidos: str):
    """
    Decorador: exige sesión iniciada Y que el rol del usuario esté en
    `roles_permitidos`. Si no hay sesión, redirige a /login (igual que
    @login_required). Si hay sesión pero el rol no alcanza, 403.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if not current_user.tiene_rol(*roles_permitidos):
                logger.warning("Acceso denegado: usuario=%s rol=%s intentó %s (requiere %s)",
                                current_user.username, current_user.rol, request.path, roles_permitidos)
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
