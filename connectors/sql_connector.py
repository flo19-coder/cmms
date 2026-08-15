"""
Conector SQL genérico — reemplaza tener que escribir una clase Python
por cada base de datos empresarial. Soporta cualquier motor con driver
SQLAlchemy (Postgres, MySQL, SQL Server, Oracle...); cuál usar y qué
consultar se define 100% en un archivo de configuración JSON en
connectors/config/sql_sources/<nombre>.json — cero código nuevo por
fuente SQL agregada.

Config de ejemplo (connectors/config/sql_sources/erp_mysql_demo.json):
{
  "name": "erp_mysql_demo",
  "dialect": "mysql+pymysql",
  "connection_env_var": "ERP_MYSQL_URL",
  "entities": {
    "equipos": {
      "query": "SELECT * FROM equipos WHERE updated_at > :updated_since",
      "incremental": true
    }
  }
}

`connection_env_var` apunta a una variable de entorno con la URL de
conexión completa (ej. mysql+pymysql://user:pass@host:3306/db) — así el
config JSON queda libre de credenciales y se puede versionar en git.

Instalar: pip install sqlalchemy  (+ el driver del motor: pymysql,
pyodbc para SQL Server, oracledb para Oracle — psycopg2 ya es dependencia)
"""
from __future__ import annotations

import os
from typing import Any, Iterator

from connectors.base import ConnectorError


class SqlConnector:
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "sql_connector")
        self.entities: dict = config.get("entities", {})

        env_var = config.get("connection_env_var")
        if not env_var or env_var not in os.environ:
            raise ConnectorError(
                f"[{self.name}] Falta la variable de entorno '{env_var}' con la URL de conexión."
            )

        try:
            import sqlalchemy
        except ImportError as e:
            raise ConnectorError("Falta 'sqlalchemy' — pip install sqlalchemy") from e

        self._engine = sqlalchemy.create_engine(os.environ[env_var], pool_pre_ping=True)
        self._sqlalchemy = sqlalchemy

    def extract(self, entity: str, updated_since: str | None = None, **kwargs: Any) -> Iterator[dict]:
        entity_cfg = self.entities.get(entity)
        if not entity_cfg:
            raise ConnectorError(
                f"[{self.name}] Entidad '{entity}' no está definida en el config "
                f"(entidades disponibles: {list(self.entities)})"
            )

        params = {}
        if entity_cfg.get("incremental"):
            params["updated_since"] = updated_since or "1970-01-01"

        stmt = self._sqlalchemy.text(entity_cfg["query"])
        with self._engine.connect() as conn:
            result = conn.execute(stmt, params)
            for row in result.mappings():
                yield dict(row)

    @classmethod
    def from_config_file(cls, path: str) -> "SqlConnector":
        import json
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))
