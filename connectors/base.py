"""
Interfaz común que deben cumplir los conectores NUEVOS del motor ETL
genérico (SqlConnector, ApiConnector, FileConnector...). Es el "átomo"
base de la arquitectura ETL (ver docs/ARQUITECTURA_ETL.md).

FracttalClient/DemoFracttalClient (connectors/fracttal_client.py,
demo_data_generator.py) NO se reescriben para implementar esto — el DAG
los sigue llamando por getattr(client, "get_x")() porque ya funcionan y
tocarlos no aporta nada. Esta interfaz es para que TODO conector nuevo
sea intercambiable entre sí sin que el DAG necesite saber de qué tipo es.
"""
from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class SourceConnector(Protocol):
    """
    Todo conector nuevo expone un único método: `extract`. Recibe el
    nombre de la entidad a extraer (definido por el config del conector,
    ej. "activos", "equipos_erp") y devuelve un iterable de registros
    crudos (dict) — el mismo contrato que ya usan `get_activos()`,
    `get_ordenes_trabajo()`, etc. en fracttal_client.py, solo que
    genérico en el nombre de la entidad en vez de un método por entidad.
    """

    def extract(self, entity: str, updated_since: str | None = None, **kwargs: Any) -> Iterator[dict]:
        ...


class ConnectorError(Exception):
    """Error de extracción de un conector (conexión, auth, config inválido)."""
