"""
Aplica sql/schema/*.sql (en orden) contra CMMS_DW_*. Necesario en Render
porque ahí no existe el mecanismo `docker-entrypoint-initdb.d` que usa
Postgres local para auto-inicializarse — acá hay que correrlo a mano
(o, como en el startCommand de render.yaml, en cada arranque). Es
seguro correrlo repetidas veces: todo el esquema usa
`CREATE TABLE/SCHEMA/INDEX IF NOT EXISTS` y `CREATE OR REPLACE VIEW`.

Uso:
    python3 scripts/bootstrap_schema.py
"""
import glob
import os

import psycopg2

DB_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql", "schema")


def main():
    archivos = sorted(glob.glob(os.path.join(SCHEMA_DIR, "*.sql")))
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for path in archivos:
                with open(path, "r", encoding="utf-8") as f:
                    sql = f.read()
                print(f"Aplicando {os.path.basename(path)}...")
                cur.execute(sql)
    finally:
        conn.close()
    print(f"Esquema aplicado correctamente ({len(archivos)} archivo(s)).")


if __name__ == "__main__":
    main()
