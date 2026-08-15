"""
Validación automática de TODOS los configs del motor ETL (conectores +
mappings de transformación) contra JSON Schema. Se corre como paso
previo en `airflow-init` (ver docker-compose.yml) — si un config está
mal armado, el stack falla acá con un mensaje claro, en vez de que un
DAG explote a medias en producción con un error críptico.

Uso manual:
    python -m connectors.config_validator
"""
from __future__ import annotations

import glob
import json
import os

from connectors.base import ConnectorError

SQL_CONNECTOR_SCHEMA = {
    "type": "object",
    "required": ["connection_env_var", "entities"],
    "properties": {
        "name": {"type": "string"},
        "dialect": {"type": "string"},
        "connection_env_var": {"type": "string"},
        "entities": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "incremental": {"type": "boolean"},
                },
            },
        },
    },
}

API_CONNECTOR_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "anyOf": [{"required": ["base_url"]}, {"required": ["base_url_env_var"]}],
    "properties": {
        "name": {"type": "string"},
        "protocol": {"type": "string", "enum": ["rest", "jsonrpc"]},
        "base_url": {"type": "string"},
        "base_url_env_var": {"type": "string"},
        "auth": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": ["none", "api_key", "bearer_env", "oauth2_client_credentials"]}
            },
        },
        "entities": {"type": "object", "minProperties": 1},
    },
}

FILE_CONNECTOR_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "name": {"type": "string"},
        "entities": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "enum": ["csv", "excel", "json"]},
                },
            },
        },
    },
}

# Formaliza la estructura que transform/postgres_loader.py ya asume
# implícitamente (module, target_table, conflict_key, mapping...) —
# ver transform/config/activos.json como referencia de config válido.
TRANSFORM_MAPPING_SCHEMA = {
    "type": "object",
    "required": ["module", "target_table", "conflict_key", "mapping"],
    "properties": {
        "module": {"type": "string"},
        "target_table": {"type": "string", "pattern": r"^[a-z_]+\.[a-z_]+$"},
        "conflict_key": {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}, "minItems": 1},
            ]
        },
        "mapping": {"type": "object", "minProperties": 1},
        "validation_schema": {"type": "object"},
        "event_rules": {"type": "object"},
        "events": {"type": "object"},
    },
}


def validate_config(config: dict, schema: dict, context: str) -> None:
    from jsonschema import validate, ValidationError
    try:
        validate(instance=config, schema=schema)
    except ValidationError as e:
        ruta = ".".join(str(p) for p in e.path) or "(raíz)"
        raise ConnectorError(f"{context}: {e.message} (en '{ruta}')") from e


def validate_all_configs(base_dir: str = "/opt/airflow") -> int:
    """
    Valida todos los .json bajo connectors/config/{sql,api,file}_sources/
    y transform/config/. Lanza ConnectorError con TODOS los problemas
    encontrados (no solo el primero) si hay alguno. Devuelve la cantidad
    de configs validados correctamente.
    """
    checks = [
        (os.path.join(base_dir, "connectors/config/sql_sources/*.json"), SQL_CONNECTOR_SCHEMA),
        (os.path.join(base_dir, "connectors/config/api_sources/*.json"), API_CONNECTOR_SCHEMA),
        (os.path.join(base_dir, "connectors/config/file_sources/*.json"), FILE_CONNECTOR_SCHEMA),
        (os.path.join(base_dir, "transform/config/*.json"), TRANSFORM_MAPPING_SCHEMA),
    ]

    errores: list[str] = []
    total_validados = 0
    for pattern, schema in checks:
        for path in sorted(glob.glob(pattern)):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except json.JSONDecodeError as e:
                    errores.append(f"{path}: JSON inválido — {e}")
                    continue
            try:
                validate_config(config, schema, path)
                total_validados += 1
            except ConnectorError as e:
                errores.append(str(e))

    if errores:
        raise ConnectorError("Se encontraron configs inválidos:\n  - " + "\n  - ".join(errores))
    return total_validados


if __name__ == "__main__":
    n = validate_all_configs()
    print(f"OK — {n} config(s) validados correctamente.")
