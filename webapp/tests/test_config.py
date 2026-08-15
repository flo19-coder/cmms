"""
Fase 0 / AC-G06 (ESPECIFICACION_CMMS_CODEX.md): "Ningún ambiente
productivo inicia con claves o usuarios demo". Prueba webapp/config.py
de forma aislada (sin Flask ni Postgres), reimportando el módulo con
distintos `CMMS_ENV` para no depender del orden de ejecución de otros
tests que ya hayan importado `app`/`api`.

Ejecutar: cd webapp && python3 -m pytest tests/test_config.py -v
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _reload_config(monkeypatch, **env):
    for key in ("CMMS_ENV",):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if "config" in sys.modules:
        del sys.modules["config"]
    return importlib.import_module("config")


def test_development_sin_variable_usa_default(monkeypatch):
    monkeypatch.delenv("CMMS_SECRET_KEY", raising=False)
    config = _reload_config(monkeypatch, CMMS_ENV="development")
    assert config.require_secret("CMMS_SECRET_KEY", "valor-dev") == "valor-dev"


def test_development_respeta_variable_si_esta_seteada(monkeypatch):
    config = _reload_config(monkeypatch, CMMS_ENV="development", CMMS_SECRET_KEY="lo-que-sea")
    assert config.require_secret("CMMS_SECRET_KEY", "valor-dev") == "lo-que-sea"


def test_production_sin_variable_falla(monkeypatch):
    monkeypatch.delenv("CMMS_SECRET_KEY", raising=False)
    config = _reload_config(monkeypatch, CMMS_ENV="production")
    with pytest.raises(RuntimeError, match="CMMS_ENV=production"):
        config.require_secret("CMMS_SECRET_KEY", "valor-dev")


def test_production_con_variable_seteada_ok(monkeypatch):
    config = _reload_config(monkeypatch, CMMS_ENV="production", CMMS_SECRET_KEY="un-secreto-real-fuerte")
    assert config.require_secret("CMMS_SECRET_KEY", "valor-dev") == "un-secreto-real-fuerte"


def test_is_production_flag(monkeypatch):
    assert _reload_config(monkeypatch, CMMS_ENV="production").IS_PRODUCTION is True
    assert _reload_config(monkeypatch, CMMS_ENV="development").IS_PRODUCTION is False
