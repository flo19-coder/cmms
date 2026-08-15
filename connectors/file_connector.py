"""
Conector de archivos locales — CSV, Excel (.xlsx) y JSON. Reemplaza la
necesidad de un servicio de nube pago (Azure Blob Storage, S3, etc.)
para el caso de uso "recibir información exportada de otro sistema":
alguien deja un archivo en una carpeta local y el pipeline lo levanta.

Config de ejemplo (connectors/config/file_sources/import_local_demo.json):
{
  "name": "import_local_demo",
  "entities": {
    "repuestos_import": {
      "path": "/opt/airflow/import/repuestos_nuevos.csv",
      "type": "csv"
    }
  }
}

`type` es opcional — si falta, se infiere de la extensión del archivo
(.csv, .xlsx/.xls, .json). Para Excel, "sheet" (opcional) elige la hoja
por nombre; si falta, usa la hoja activa. Para JSON, si el archivo raíz
es un objeto (no una lista), "items_key" (opcional, default "items")
indica la clave que contiene el arreglo de registros.

Instalar: pip install openpyxl   (CSV y JSON no necesitan dependencias extra)
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any, Iterator

from connectors.base import ConnectorError

_EXT_TO_TYPE = {".csv": "csv", ".xlsx": "excel", ".xls": "excel", ".json": "json"}


class FileConnector:
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "file_connector")
        self.entities: dict = config.get("entities", {})

    def extract(self, entity: str, updated_since: str | None = None, **kwargs: Any) -> Iterator[dict]:
        entity_cfg = self.entities.get(entity)
        if not entity_cfg:
            raise ConnectorError(
                f"[{self.name}] Entidad '{entity}' no está definida en el config "
                f"(entidades disponibles: {list(self.entities)})"
            )

        path = entity_cfg["path"]
        if not os.path.exists(path):
            raise ConnectorError(f"[{self.name}] Archivo no encontrado: {path}")

        file_type = entity_cfg.get("type") or _EXT_TO_TYPE.get(os.path.splitext(path)[1].lower())
        if file_type == "csv":
            yield from self._read_csv(path, entity_cfg)
        elif file_type == "excel":
            yield from self._read_excel(path, entity_cfg)
        elif file_type == "json":
            yield from self._read_json(path, entity_cfg)
        else:
            raise ConnectorError(f"[{self.name}] Tipo de archivo no soportado para '{path}'")

    @staticmethod
    def _read_csv(path: str, cfg: dict) -> Iterator[dict]:
        with open(path, newline="", encoding=cfg.get("encoding", "utf-8")) as f:
            reader = csv.DictReader(f, delimiter=cfg.get("delimiter", ","))
            for row in reader:
                yield dict(row)

    @staticmethod
    def _read_excel(path: str, cfg: dict) -> Iterator[dict]:
        try:
            import openpyxl
        except ImportError as e:
            raise ConnectorError("Falta 'openpyxl' — pip install openpyxl") from e

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = wb[cfg["sheet"]] if cfg.get("sheet") else wb.active
        rows = sheet.iter_rows(values_only=True)
        header = [str(h) for h in next(rows)]
        for row in rows:
            if all(v is None for v in row):
                continue
            yield dict(zip(header, row))

    @staticmethod
    def _read_json(path: str, cfg: dict) -> Iterator[dict]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get(cfg.get("items_key", "items"), [])
        yield from items

    @classmethod
    def from_config_file(cls, path: str) -> "FileConnector":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))
