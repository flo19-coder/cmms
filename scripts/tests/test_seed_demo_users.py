"""
Fase 0 / AC-G06 (ESPECIFICACION_CMMS_CODEX.md): "Ningún ambiente
productivo inicia con claves o usuarios demo". No toca Postgres --
prueba solo la función pura de decisión de scripts/seed_demo_users.py.

Ejecutar: python3 -m pytest scripts/tests/ -v   (desde la raíz del repo)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seed_demo_users import debe_omitir_seed


def test_development_nunca_se_omite():
    assert debe_omitir_seed("development", "") is False
    assert debe_omitir_seed("development", "false") is False


def test_production_sin_autorizacion_se_omite():
    assert debe_omitir_seed("production", "") is True
    assert debe_omitir_seed("production", "false") is True


def test_production_con_autorizacion_explicita_no_se_omite():
    assert debe_omitir_seed("production", "true") is False
    assert debe_omitir_seed("production", "TRUE") is False


def test_mayusculas_y_espacios_no_rompen_la_regla():
    assert debe_omitir_seed("  PRODUCTION  ", "true") is False
    assert debe_omitir_seed("Production", "") is True
