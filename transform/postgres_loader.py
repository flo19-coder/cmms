"""
Loader genérico: toma un iterable de registros crudos + un config JSON
de mapeo/validación, y hace upsert en la tabla `core.*` destino.

Se usa igual desde cualquier DAG, cambiando solo el config y el
iterable de origen (API real o demo).
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

import psycopg2
import psycopg2.extras
from jsonschema import validate, ValidationError

from transform.json_logic_engine import transform_record

logger = logging.getLogger(__name__)


def load_module(
    records: Iterable[dict],
    config: dict,
    conn_params: dict,
    batch_id: str,
    module_name: str,
) -> dict:
    """
    Retorna un resumen: {"total": N, "cargados": N, "rechazados": N, "eventos": [...]}
    """
    schema = config.get("validation_schema")
    mapping = config["mapping"]
    target_table = config["target_table"]
    conflict_key = config["conflict_key"]
    # conflict_key puede ser un string (columna única) o una lista
    # (clave compuesta, ej. lecturas de medidor: [medidor_id, fecha_lectura])
    conflict_cols = [conflict_key] if isinstance(conflict_key, str) else list(conflict_key)
    event_rules = config.get("event_rules", {})
    events_config = config.get("events", {})

    rows_to_insert = []
    rejected = 0
    triggered_events = []

    for raw in records:
        if schema:
            try:
                validate(instance=raw, schema=schema)
            except ValidationError as e:
                rejected += 1
                logger.warning("Registro rechazado (%s): %s", module_name, e.message)
                continue

        transformed = transform_record(raw, mapping)
        rows_to_insert.append(transformed)

        record_key = tuple(transformed.get(c) for c in conflict_cols) if len(conflict_cols) > 1 else transformed.get(conflict_cols[0])
        for event_name, rule in event_rules.items():
            from transform.json_logic_engine import apply_rule
            if apply_rule(rule, raw):
                triggered_events.append({"event": event_name, "record": record_key})

    if not rows_to_insert:
        return {"total": 0, "cargados": 0, "rechazados": rejected, "eventos": triggered_events}

    columns = list(rows_to_insert[0].keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in conflict_cols)
    conflict_target = ", ".join(conflict_cols)

    # Si no hay columnas para actualizar (todas forman la clave), usar DO NOTHING
    conflict_action = f"DO UPDATE SET {update_set}" if update_set else "DO NOTHING"

    upsert_sql = f"""
        INSERT INTO {target_table} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_target}) {conflict_action}
    """

    conn = psycopg2.connect(**conn_params)
    try:
        with conn.cursor() as cur:
            values = [[row.get(c) for c in columns] for row in rows_to_insert]
            psycopg2.extras.execute_batch(cur, upsert_sql, values, page_size=200)
        conn.commit()
    finally:
        conn.close()

    return {
        "total": rejected + len(rows_to_insert),
        "cargados": len(rows_to_insert),
        "rechazados": rejected,
        "eventos": triggered_events,
    }


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
