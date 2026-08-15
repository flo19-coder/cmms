"""
Crea las 4 cuentas demo (una por rol) para poder probar el sistema de
login sin tener que crear usuarios a mano primero.

**Solo para el entorno de demo/desarrollo local.** Antes de usar esto
con la clínica de verdad: correr `manage_users.py deactivate` sobre
estas 4 cuentas y crear las reales con `manage_users.py create`.

Fase 0 / AC-G06 (ESPECIFICACION_CMMS_CODEX.md) -- "Ningún ambiente
productivo inicia con claves o usuarios demo": si CMMS_ENV=production,
este script se niega a crear los usuarios demo por defecto. Si es una
decisión consciente del dueño del producto (ej. una demo pública
temporal), hay que setear CMMS_ALLOW_DEMO_SEED=true explícitamente
-- ver sección 21 de la especificación ("decisiones que el dueño del
producto debe confirmar antes de producción").

Uso:
    python3 scripts/seed_demo_users.py
"""
import os
import sys

import psycopg2
from werkzeug.security import generate_password_hash

DB_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}

DEMO_USERS = [
    ("admin", "admin123", "Administrador Demo", "ADMIN"),
    ("supervisor", "super123", "Supervisor Demo", "SUPERVISOR"),
    ("tecnico", "tecnico123", "Técnico Demo", "TECNICO"),
    ("operador", "operador123", "Operador Demo", "OPERADOR"),
]


def debe_omitir_seed(cmms_env: str, allow_demo_seed_raw: str) -> bool:
    """Puro / testeable sin DB -- ver webapp/tests/test_config.py."""
    return cmms_env.strip().lower() == "production" and allow_demo_seed_raw.strip().lower() != "true"


def main():
    cmms_env = os.environ.get("CMMS_ENV", "development")
    if debe_omitir_seed(cmms_env, os.environ.get("CMMS_ALLOW_DEMO_SEED", "")):
        print(
            "CMMS_ENV=production: no se crean usuarios demo por defecto "
            "(ver ESPECIFICACION_CMMS_CODEX.md, AC-G06). Si es una decisión "
            "consciente del dueño del producto, setea CMMS_ALLOW_DEMO_SEED=true."
        )
        return

    conn = psycopg2.connect(**DB_PARAMS)
    creados = 0
    try:
        with conn.cursor() as cur:
            for username, password, nombre, rol in DEMO_USERS:
                cur.execute("SELECT 1 FROM core.usuario WHERE username = %s", (username,))
                if cur.fetchone():
                    print(f"'{username}' ya existe, se omite.")
                    continue
                cur.execute(
                    "INSERT INTO core.usuario (username, password_hash, nombre_completo, rol) "
                    "VALUES (%s, %s, %s, %s)",
                    (username, generate_password_hash(password), nombre, rol),
                )
                creados += 1
                print(f"Creado: {username} / {password} (rol {rol})")
        conn.commit()
    finally:
        conn.close()
    print(f"\n{creados} usuario(s) demo creado(s). RECORDATORIO: desactivar/cambiar antes de producción.")


if __name__ == "__main__":
    main()
