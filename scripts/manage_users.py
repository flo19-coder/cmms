"""
Gestión de usuarios del CMMS por línea de comandos.

Uso:
    python3 scripts/manage_users.py create --username admin --nombre "Admin Principal" --rol ADMIN
    python3 scripts/manage_users.py create --username jperez --nombre "Juan Pérez" --rol TECNICO
    python3 scripts/manage_users.py list
    python3 scripts/manage_users.py deactivate --username jperez
    python3 scripts/manage_users.py reset-password --username jperez

Si no se pasa --password, se pide interactivo (getpass, no queda en el
historial de la shell ni en logs).

Requiere las mismas variables de entorno que la webapp (CMMS_DW_HOST,
etc.) — por defecto asume que corres esto desde tu máquina contra
localhost:5432 (el puerto que expone docker-compose).
"""
import argparse
import getpass
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

ROLES_VALIDOS = ["ADMIN", "SUPERVISOR", "TECNICO", "OPERADOR"]


def get_password(args) -> str:
    if args.password:
        return args.password
    pw1 = getpass.getpass("Contraseña: ")
    pw2 = getpass.getpass("Repetir contraseña: ")
    if pw1 != pw2:
        print("Las contraseñas no coinciden.", file=sys.stderr)
        sys.exit(1)
    if len(pw1) < 8:
        print("La contraseña debe tener al menos 8 caracteres.", file=sys.stderr)
        sys.exit(1)
    return pw1


def cmd_create(args):
    if args.rol not in ROLES_VALIDOS:
        print(f"Rol inválido. Debe ser uno de: {ROLES_VALIDOS}", file=sys.stderr)
        sys.exit(1)
    password = get_password(args)
    password_hash = generate_password_hash(password)

    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO core.usuario (username, password_hash, nombre_completo, rol) "
                "VALUES (%s, %s, %s, %s)",
                (args.username, password_hash, args.nombre, args.rol),
            )
        conn.commit()
        print(f"Usuario '{args.username}' creado con rol {args.rol}.")
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        print(f"Ya existe un usuario con username '{args.username}'.", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def cmd_list(args):
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, nombre_completo, rol, activo, ultimo_login "
                "FROM core.usuario ORDER BY rol, username"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("Sin usuarios registrados todavía.")
        return
    print(f"{'USUARIO':<20} {'NOMBRE':<28} {'ROL':<12} {'ACTIVO':<8} ÚLTIMO LOGIN")
    for username, nombre, rol, activo, ultimo_login in rows:
        print(f"{username:<20} {nombre:<28} {rol:<12} {'sí' if activo else 'no':<8} {ultimo_login or '—'}")


def cmd_deactivate(args):
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.usuario SET activo = FALSE WHERE username = %s", (args.username,))
            if cur.rowcount == 0:
                print(f"No existe usuario '{args.username}'.", file=sys.stderr)
                sys.exit(1)
        conn.commit()
        print(f"Usuario '{args.username}' desactivado.")
    finally:
        conn.close()


def cmd_reset_password(args):
    password = get_password(args)
    password_hash = generate_password_hash(password)
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.usuario SET password_hash = %s WHERE username = %s", (password_hash, args.username))
            if cur.rowcount == 0:
                print(f"No existe usuario '{args.username}'.", file=sys.stderr)
                sys.exit(1)
        conn.commit()
        print(f"Contraseña de '{args.username}' actualizada.")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Gestión de usuarios del CMMS")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Crear un usuario nuevo")
    p_create.add_argument("--username", required=True)
    p_create.add_argument("--nombre", required=True)
    p_create.add_argument("--rol", required=True, choices=ROLES_VALIDOS)
    p_create.add_argument("--password", help="Si se omite, se pide interactivo (recomendado)")
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="Listar usuarios")
    p_list.set_defaults(func=cmd_list)

    p_deact = sub.add_parser("deactivate", help="Desactivar un usuario (no lo borra)")
    p_deact.add_argument("--username", required=True)
    p_deact.set_defaults(func=cmd_deactivate)

    p_reset = sub.add_parser("reset-password", help="Cambiar la contraseña de un usuario")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", help="Si se omite, se pide interactivo (recomendado)")
    p_reset.set_defaults(func=cmd_reset_password)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
