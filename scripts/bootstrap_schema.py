"""
Aplica sql/schema/*.sql (en orden) contra CMMS_DW_*, y despues
sincroniza Alembic. Necesario en Render porque ahí no existe el
mecanismo `docker-entrypoint-initdb.d` que usa Postgres local para
auto-inicializarse — acá hay que correrlo a mano (o, como en el
startCommand de render.yaml, en cada arranque). Aplicar el SQL es
seguro de repetir: todo el esquema usa
`CREATE TABLE/SCHEMA/INDEX IF NOT EXISTS` y `CREATE OR REPLACE VIEW`.

Sincronización de Alembic -- CORREGIDO (antes hacía `alembic stamp
head` incondicional en cada arranque, lo cual es peligroso en cuanto
exista una migración real después de `0001_baseline`: `stamp` NO
ejecuta el contenido de la migración, solo escribe el número de
revisión, así que una `0002` quedaría "marcada como aplicada" sin
haber corrido nunca):

  1. Si la base NO tiene ninguna revisión de Alembic registrada todavía
     (recién creada, o preexistente de antes de introducir Alembic en
     este repo): se marca en `0001_baseline` -- esa revisión representa
     exactamente el estado que `aplicar_schema_sql()` acaba de
     garantizar, nunca "head" a ciegas.
  2. Siempre, después, se corre `alembic upgrade head` -- así cualquier
     migración real posterior a la baseline (`0002`, `0003`...) SÍ se
     ejecuta de verdad la primera vez que el proceso arranca con ella
     presente.
  3. Si la base ya tenía una revisión, el paso 1 se salta por completo
     (nunca se vuelve a hacer `stamp`) y solo corre el `upgrade head`
     del paso 2, que es un no-op seguro si ya está al día.

Ver scripts/tests/test_bootstrap_alembic_integration.py para la prueba
contra Postgres real que demuestra el punto 2.

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


def _tiene_revision_alembic() -> bool:
    """True si la base ya tiene una fila en `alembic_version` (esté o
    no la tabla creada todavía cuenta como "no tiene revisión")."""
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'alembic_version')"
            )
            if not cur.fetchone()[0]:
                return False
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            return cur.fetchone() is not None
    finally:
        conn.close()


def _alembic_config() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "alembic"))
    return cfg


def sincronizar_alembic() -> None:
    cfg = _alembic_config()
    if _tiene_revision_alembic():
        print("La base ya tiene una revisión de Alembic registrada -- no se vuelve a stampear.")
    else:
        print("La base no tiene revisión de Alembic todavía -- marcando '0001_baseline'.")
        command.stamp(cfg, "0001_baseline")
    command.upgrade(cfg, "head")


def main():
    n = aplicar_schema_sql()
    print(f"Esquema aplicado correctamente ({n} archivo(s)).")
    sincronizar_alembic()
    print("Alembic sincronizado (stamp condicional + upgrade head).")


if __name__ == "__main__":
    main()
