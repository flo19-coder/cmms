"""
DAG factory — genera un DAG por módulo del CMMS (Activos, OTs, Tareas,
Medidores, Almacenes, RRHH) a partir de los configs JSON en
transform/config/*.json.

Modo demo vs producción se controla 100% por variable de entorno
CMMS_USE_DEMO_DATA (ver docker-compose.yml). El resto del pipeline
(transform, validate, load) es idéntico en ambos casos.

Nivel "Atomic Design" de este archivo: TEMPLATE (genera N DAGs = N
"páginas" a partir de una sola plantilla parametrizada por config).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

CONFIG_DIR = Path("/opt/airflow/transform/config")
USE_DEMO = os.environ.get("CMMS_USE_DEMO_DATA", "true").lower() == "true"

DW_CONN_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "postgres_dw"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", ""),
}

DEFAULT_ARGS = {
    "owner": "cmms-clinica",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

# Mapea nombre de módulo -> método del cliente (real o demo) que lo produce.
# "lecturas_medidor" NO está acá porque necesita un extractor especial
# (loop por cada medidor + rango de fechas) — ver _extract_lecturas_medidor.
MODULE_SOURCE_METHOD = {
    "activos": "get_activos",
    "ordenes_trabajo": "get_ordenes_trabajo",
    "tareas": "get_tareas",
    "medidores": "get_medidores",
    "almacenes": "get_almacenes",
    "recursos_humanos": "get_recursos_humanos",
    "repuestos_usados": "get_repuestos_usados",
}

# Módulos "simples" (1 DAG = 1 tarea) + su frecuencia (sección 4 del doc
# de arquitectura). "medidores"/"lecturas_medidor" NO están acá: van en
# un DAG combinado propio porque lecturas depende de que el catálogo de
# medidores ya exista (FK), ver build_dag_medidores().
#
# ORDEN DE DEPENDENCIA (por FK) para la primera corrida manual:
#   1) activos
#   2) ordenes_trabajo, tareas, almacenes, recursos_humanos (cualquier orden)
#   3) repuestos_usados (necesita ordenes_trabajo Y almacenes ya cargados)
MODULE_SCHEDULES = {
    "activos": "@daily",
    "ordenes_trabajo": "0 */2 * * *",     # cada 2 horas
    "tareas": "0 */2 * * *",
    "almacenes": "@daily",                # catálogos, cambian poco
    "recursos_humanos": "@daily",
    "repuestos_usados": "0 */3 * * *",    # cada 3 horas — depende de OTs + almacenes
    # Motor ETL genérico (ver docs/ARQUITECTURA_ETL.md) — NO usa el cliente
    # Fracttal/demo, usa connectors/sql_connector.py contra el mysql_demo
    # (ERP externo simulado). Demuestra que el mismo pipeline sirve para
    # cualquier fuente, no solo Fracttal.
    "equipos_sede_externa": "0 */6 * * *",  # cada 6 horas
    "tareas_jsonrpc_demo": "0 */4 * * *",   # cada 4 horas — vía JSON-RPC 2.0
    "repuestos_import_csv": "0 */12 * * *",  # cada 12 horas — vía archivo CSV local
}

SQL_SOURCE_CONFIG_PATH = "/opt/airflow/connectors/config/sql_sources/erp_mysql_demo.json"
API_SOURCE_CONFIG_PATH = "/opt/airflow/connectors/config/api_sources/mock_jsonrpc_demo.json"
FILE_SOURCE_CONFIG_PATH = "/opt/airflow/connectors/config/file_sources/import_local_demo.json"


def _get_client():
    if USE_DEMO:
        from connectors.demo_data_generator import DemoFracttalClient
        return DemoFracttalClient(seed=42)
    else:
        from connectors.fracttal_client import client_from_env
        return client_from_env()


def _records_for_module(module_name: str, client):
    """
    Devuelve el iterable de registros crudos para un módulo. La mayoría
    son un simple getattr(client, method)(), pero "lecturas_medidor" es
    especial: primero hay que listar los medidores y luego pedir las
    lecturas de CADA UNO en un rango de fechas.
    """
    if module_name == "lecturas_medidor":
        from datetime import datetime, timedelta
        desde = (datetime.now() - timedelta(days=2)).isoformat()
        hasta = datetime.now().isoformat()
        for medidor in client.get_medidores():
            yield from client.get_lecturas_medidor(medidor["medidor_id"], desde, hasta)
    elif module_name == "equipos_sede_externa":
        from connectors.sql_connector import SqlConnector
        connector = SqlConnector.from_config_file(SQL_SOURCE_CONFIG_PATH)
        yield from connector.extract("equipos")
    elif module_name == "tareas_jsonrpc_demo":
        from connectors.api_connector import ApiConnector
        connector = ApiConnector.from_config_file(API_SOURCE_CONFIG_PATH)
        yield from connector.extract("tareas_externas")
    elif module_name == "repuestos_import_csv":
        from connectors.file_connector import FileConnector
        connector = FileConnector.from_config_file(FILE_SOURCE_CONFIG_PATH)
        yield from connector.extract("repuestos_import")
    else:
        method_name = MODULE_SOURCE_METHOD[module_name]
        yield from getattr(client, method_name)()


def _extract_transform_load(module_name: str, **context):
    import logging
    from transform.postgres_loader import load_module, load_config

    logger = logging.getLogger("cmms_pipeline")
    batch_id = str(uuid.uuid4())

    config = load_config(str(CONFIG_DIR / f"{module_name}.json"))
    client = _get_client()
    records = _records_for_module(module_name, client)

    summary = load_module(
        records=records,
        config=config,
        conn_params=DW_CONN_PARAMS,
        batch_id=batch_id,
        module_name=module_name,
    )

    logger.info("Módulo=%s batch=%s resumen=%s", module_name, batch_id, json.dumps(summary))

    if summary["eventos"]:
        from transform.events import dispatch_events
        dispatch_events(summary["eventos"], config.get("events", {}), module_name, DW_CONN_PARAMS)
        logger.warning("Eventos disparados en %s: %s", module_name, summary["eventos"])

    context["ti"].xcom_push(key="summary", value=summary)
    return summary


def build_dag(module_name: str, schedule: str) -> DAG:
    with DAG(
        dag_id=f"cmms_{module_name}",
        default_args=DEFAULT_ARGS,
        description=f"Pipeline ETL — módulo {module_name} (demo={USE_DEMO})",
        schedule_interval=schedule,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        # El proyecto usa un dataset curado (solo Sede Lima) para la demo;
        # estos DAGs generan datos sintéticos de las 5 sedes originales y
        # los sobrescribirían en cada corrida. Pausados por defecto -- si
        # se necesita volver a generar datos multi-sede, despausar a mano.
        is_paused_upon_creation=True,
        tags=["cmms", "clinica", "demo" if USE_DEMO else "produccion"],
    ) as dag:
        PythonOperator(
            task_id=f"extract_transform_load_{module_name}",
            python_callable=_extract_transform_load,
            op_kwargs={"module_name": module_name},
        )
    return dag


def build_dag_medidores() -> DAG:
    """
    DAG combinado: primero carga el catálogo de medidores, luego las
    lecturas — en ese orden, dentro del mismo DAG, porque
    core.lectura_medidor tiene FK a core.medidor.
    """
    with DAG(
        dag_id="cmms_medidores",
        default_args=DEFAULT_ARGS,
        description=f"Pipeline ETL — medidores + lecturas (demo={USE_DEMO})",
        schedule_interval="*/30 * * * *",   # cada 30 min — dato casi tiempo real
        start_date=datetime(2026, 1, 1),
        catchup=False,
        is_paused_upon_creation=True,  # ver comentario en build_dag()
        tags=["cmms", "clinica", "monitoreo", "demo" if USE_DEMO else "produccion"],
    ) as dag:
        t_catalogo = PythonOperator(
            task_id="extract_transform_load_medidores",
            python_callable=_extract_transform_load,
            op_kwargs={"module_name": "medidores"},
        )
        t_lecturas = PythonOperator(
            task_id="extract_transform_load_lecturas_medidor",
            python_callable=_extract_transform_load,
            op_kwargs={"module_name": "lecturas_medidor"},
        )
        t_catalogo >> t_lecturas
    return dag


# Registrar un DAG por cada config JSON "simple" disponible en transform/config/
_globals = globals()
for _module, _schedule in MODULE_SCHEDULES.items():
    _config_path = CONFIG_DIR / f"{_module}.json"
    if _config_path.exists():
        _globals[f"dag_cmms_{_module}"] = build_dag(_module, _schedule)

# DAG combinado de medidores (solo si ambos configs existen)
if (CONFIG_DIR / "medidores.json").exists() and (CONFIG_DIR / "lecturas_medidor.json").exists():
    _globals["dag_cmms_medidores"] = build_dag_medidores()
