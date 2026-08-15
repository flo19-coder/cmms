"""
Aplica sql/schema/*.sql (en orden) contra CMMS_DW_*, y despues marca la
base en el baseline de Alembic (`alembic stamp head` -- ver alembic/
env.py y ESPECIFICACION_CMMS_CODEX.md sección 10.5). Necesario en
Render porque ahí no existe el mecanismo `docker-entrypoint-initdb.d`
que usa Postgres local para auto-inicializarse — acá hay que correrlo a
mano (o, como en el startCommand de render.yaml, en cada arranque). Es
seguro correrlo repetidas veces: todo el esquema usa
`CREATE TABLE/SCHEMA/INDEX IF NOT EXISTS` y `CREATE OR REPLACE VIEW`, y
`alembic stamp` es idempotente (solo escribe la revisión actual).

A partir de este paquete, cualquier cambio de esquema NUEVO se hace con
una migración de Alembic (`alembic revision -m "..."`, editar
upgrade()/downgrade() con `op.execute()`), no con otro archivo suelto
en migrations/ -- esa carpeta queda como referencia histórica de cómo
se llegó al baseline.

Uso:
    python3 scripts/bootstrap_schema.py
"""
import glob
import os

import psycopg2
from alembic import command
from alembic.config import Config

# CMMS_REPO_ROOT permite overridear la raíz del repo cuando scripts/ no
# es literalmente un subdirectorio de ella en el filesystem del proceso
# (ej. docker-compose local, donde cada carpeta se monta por separado
# como volumen -- ver docker-compose.yml, servicio webapp). Sin la
# variable, se asume el layout normal de un checkout del repo (Render).
REPO_ROOT = os.environ.get("CMMS_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}

SCHEMA_DIR = os.path.join(REPO_ROOT, "sql", "schema")


def aplicar_schema_sql() -> int:
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
    return len(archivos)


def marcar_baseline_alembic() -> None:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "alembic"))
    command.stamp(cfg, "head")


def main():
    n = aplicar_schema_sql()
    print(f"Esquema aplicado correctamente ({n} archivo(s)).")
    marcar_baseline_alembic()
    print("Base marcada en el baseline de Alembic (alembic stamp head).")


if __name__ == "__main__":
    main()
