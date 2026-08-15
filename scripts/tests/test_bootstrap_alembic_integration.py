"""
Paso 0 (corrección pedida por el dueño del producto): antes,
`scripts/bootstrap_schema.py` hacía `alembic stamp head` incondicional
en cada arranque -- peligroso en cuanto exista una migración real
después de `0001_baseline`, porque `stamp` NO ejecuta el contenido de
la migración, solo escribe el número de revisión. Estas pruebas
demuestran, contra Postgres real, que el flujo corregido:

  1. SÍ ejecuta el contenido de una migración `0002` la primera vez.
  2. Una segunda corrida no vuelve a stampear y es un no-op seguro.
  3. Una base con datos existentes los conserva intactos.

Requiere Postgres accesible via CMMS_DW_* (usuario con permiso de
CREATE DATABASE -- el mismo `cmms_admin` local ya lo tiene). Se salta
automáticamente si no hay conexión disponible.

Ejecutar: python3 -m pytest scripts/tests/test_bootstrap_alembic_integration.py -v
"""
from __future__ import annotations

import importlib
import os
import sys
import uuid

import psycopg2
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

ADMIN_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}


def _postgres_disponible() -> bool:
    try:
        conn = psycopg2.connect(dbname="postgres", **ADMIN_PARAMS)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_disponible(), reason="requiere Postgres real vía CMMS_DW_*")


def _head_real_actual() -> str:
    """
    Head real de alembic/versions/ (las migraciones YA commiteadas al
    repo, sin contar la temporal que este test va a escribir) -- la
    migración de prueba debe encadenar desde acá, no desde
    '0001_baseline' a ciegas, o choca con cualquier migración real que
    ya exista después del baseline (ej. 0002_activo_estado_lifecycle).
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"se esperaba un único head real, hay {len(heads)}: {heads}"
    return heads[0]


MIGRACION_TEST_TEMPLATE = '''"""migración de prueba -- crea una tabla marcadora para demostrar
que 'alembic upgrade head' ejecuta el CONTENIDO de la migración, no
solo avanza el puntero de revisión.

Revision ID: {revision}
Revises: {down_revision}
Create Date: 2026-01-01

"""
from __future__ import annotations

from alembic import op

revision = "{revision}"
down_revision = "{down_revision}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS _test_migracion_0002_ejecutada (id serial primary key)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _test_migracion_0002_ejecutada")
'''


@pytest.fixture
def base_de_prueba():
    nombre_db = f"test_alembic_{uuid.uuid4().hex[:8]}"
    conn = psycopg2.connect(dbname="postgres", **ADMIN_PARAMS)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre_db}"')
    conn.close()
    try:
        yield nombre_db
    finally:
        conn = psycopg2.connect(dbname="postgres", **ADMIN_PARAMS)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre_db,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre_db}"')
        conn.close()


@pytest.fixture
def con_migracion_0002_temporal():
    """
    Escribe una migración TEMPORAL en alembic/versions/, encadenada
    dinámicamente desde el head real actual (para no chocar con
    cualquier migración real que ya exista después del baseline), y la
    borra al terminar -- no debe quedar como parte del historial real.
    """
    revision_id = f"9999_test_marker_{uuid.uuid4().hex[:8]}"
    contenido = MIGRACION_TEST_TEMPLATE.format(revision=revision_id, down_revision=_head_real_actual())

    filename = f"{revision_id}.py"
    path = os.path.join(REPO_ROOT, "alembic", "versions", filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(contenido)
    try:
        yield revision_id
    finally:
        os.remove(path)
        pycache = os.path.join(REPO_ROOT, "alembic", "versions", "__pycache__")
        if os.path.isdir(pycache):
            for fn in os.listdir(pycache):
                if revision_id in fn:
                    os.remove(os.path.join(pycache, fn))


def _importar_bootstrap_apuntando_a(nombre_db: str):
    os.environ["CMMS_DW_NAME"] = nombre_db
    if "bootstrap_schema" in sys.modules:
        del sys.modules["bootstrap_schema"]
    import bootstrap_schema
    importlib.reload(bootstrap_schema)
    return bootstrap_schema


def _tabla_existe(nombre_db: str, tabla: str) -> bool:
    conn = psycopg2.connect(dbname=nombre_db, **ADMIN_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                (tabla,),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def _revision_actual(nombre_db: str) -> str | None:
    conn = psycopg2.connect(dbname=nombre_db, **ADMIN_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def test_base_nueva_ejecuta_el_contenido_de_la_migracion_0002(base_de_prueba, con_migracion_0002_temporal, monkeypatch):
    revision_esperada = con_migracion_0002_temporal
    bootstrap = _importar_bootstrap_apuntando_a(base_de_prueba)

    bootstrap.main()

    assert _tabla_existe(base_de_prueba, "_test_migracion_0002_ejecutada"), (
        "alembic upgrade head debía correr el contenido real de la migración, no solo stampearla"
    )
    assert _revision_actual(base_de_prueba) == revision_esperada


def test_segunda_corrida_no_re_stampea_y_es_no_op_seguro(base_de_prueba, con_migracion_0002_temporal, monkeypatch):
    revision_esperada = con_migracion_0002_temporal
    bootstrap = _importar_bootstrap_apuntando_a(base_de_prueba)

    bootstrap.main()  # 1ra corrida: stamp 0001_baseline + upgrade -> ejecuta la migración de prueba
    assert bootstrap._tiene_revision_alembic() is True

    bootstrap.main()  # 2da corrida: NO debe re-stampear, debe ser no-op seguro

    assert _revision_actual(base_de_prueba) == revision_esperada
    assert _tabla_existe(base_de_prueba, "_test_migracion_0002_ejecutada")


def test_base_existente_preexistente_de_antes_de_alembic_conserva_sus_datos(base_de_prueba, monkeypatch):
    """
    Simula el caso real (Render/local antes de este fix): una base que
    YA tenía datos y esquema pero SIN tabla alembic_version -- el
    primer bootstrap la marca en 0001_baseline y luego corre
    'upgrade head' (que puede avanzar más allá si ya hay migraciones
    reales en el repo, ej. 0002_activo_estado_lifecycle) SIN tocar los
    datos preexistentes de una tabla que Alembic no conoce.
    """
    conn = psycopg2.connect(dbname=base_de_prueba, **ADMIN_PARAMS)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE dato_preexistente (id serial primary key, valor text)")
        cur.execute("INSERT INTO dato_preexistente (valor) VALUES ('no tocar'), ('sigue aca')")
    conn.close()

    bootstrap = _importar_bootstrap_apuntando_a(base_de_prueba)
    bootstrap.main()

    conn = psycopg2.connect(dbname=base_de_prueba, **ADMIN_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), array_agg(valor ORDER BY id) FROM dato_preexistente")
            total, valores = cur.fetchone()
            assert total == 2
            assert valores == ["no tocar", "sigue aca"]
    finally:
        conn.close()

    # Termina en el head REAL del repo (0001_baseline es solo el punto
    # de partida del stamp condicional, no necesariamente el destino
    # final si ya existen migraciones posteriores reales).
    assert _revision_actual(base_de_prueba) == _head_real_actual()
