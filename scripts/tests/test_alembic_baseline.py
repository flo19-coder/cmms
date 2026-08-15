"""
Fase 0 (ESPECIFICACION_CMMS_CODEX.md, sección 10.5): baseline de
Alembic. No requiere Postgres -- valida que alembic.ini apunte a la
carpeta correcta y que la revisión baseline esté bien formada (id,
down_revision=None, upgrade/downgrade no-op sin efectos secundarios).

La verificación con una base real (`alembic upgrade head` / `stamp` /
`current`) se corre aparte con Postgres levantado -- ver README.md.

Ejecutar: python3 -m pytest scripts/tests/ -v   (desde la raíz del repo)
"""
import configparser
import importlib.util
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_alembic_ini_apunta_a_carpeta_alembic():
    parser = configparser.ConfigParser()
    parser.read(os.path.join(REPO_ROOT, "alembic.ini"))
    assert parser["alembic"]["script_location"] == "alembic"


def test_alembic_ini_no_tiene_url_con_password_hardcodeada():
    # Regla global 8 -- ESPECIFICACION_CMMS_CODEX.md
    parser = configparser.ConfigParser()
    parser.read(os.path.join(REPO_ROOT, "alembic.ini"))
    assert "sqlalchemy.url" not in parser["alembic"]


def _cargar_baseline():
    path = os.path.join(REPO_ROOT, "alembic", "versions", "0001_baseline.py")
    spec = importlib.util.spec_from_file_location("baseline_0001", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_es_la_raiz_de_la_cadena_de_migraciones():
    baseline = _cargar_baseline()
    assert baseline.revision == "0001_baseline"
    assert baseline.down_revision is None


def test_baseline_upgrade_downgrade_son_no_op():
    baseline = _cargar_baseline()
    assert baseline.upgrade() is None
    assert baseline.downgrade() is None
