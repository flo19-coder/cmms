"""
Conector REST/JSON-RPC genérico — reemplaza tener que escribir una
clase Python por cada API externa (como se hizo a mano en
fracttal_client.py). Habla dos protocolos, elegidos por config:

  "protocol": "jsonrpc"  -> implementa JSON-RPC 2.0 real:
      request:  {"jsonrpc": "2.0", "method": ..., "params": ..., "id": N}
      response: {"jsonrpc": "2.0", "result": ...}  o  {"jsonrpc": "2.0", "error": {...}}
      (ver https://www.jsonrpc.org/specification)

  "protocol": "rest"     -> REST/JSON plano (path + query params o body)

Config de ejemplo (connectors/config/api_sources/mock_jsonrpc_demo.json):
{
  "name": "mock_jsonrpc_demo",
  "base_url_env_var": "MOCK_JSONRPC_BASE_URL",
  "protocol": "jsonrpc",
  "auth": {"type": "none"},
  "entities": {
    "tareas_externas": {
      "method": "tareas.list",
      "params": {},
      "pagination": {"page_size": 50}
    }
  }
}

Tipos de auth soportados (bloque "auth" del config):
  {"type": "none"}
  {"type": "api_key", "header": "X-API-Key", "env_var": "MI_API_KEY"}
  {"type": "bearer_env", "env_var": "MI_TOKEN"}
  {"type": "oauth2_client_credentials", "token_url_env_var": ..., "client_id_env_var": ..., "client_secret_env_var": ...}
  (mismo patrón que fracttal_client.py, generalizado por config)
"""
from __future__ import annotations

import os
import time
from typing import Any, Iterator

from connectors.base import ConnectorError


class ApiConnector:
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "api_connector")
        self.protocol = config.get("protocol", "rest")
        self.entities: dict = config.get("entities", {})
        self.auth: dict = config.get("auth", {"type": "none"})

        base_url_env = config.get("base_url_env_var")
        if base_url_env and os.environ.get(base_url_env):
            self.base_url = os.environ[base_url_env].rstrip("/")
        elif config.get("base_url"):
            self.base_url = config["base_url"].rstrip("/")
        else:
            raise ConnectorError(f"[{self.name}] Falta 'base_url' o '{base_url_env}' en el entorno.")

        self._rpc_id = 0
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        auth_type = self.auth.get("type", "none")
        if auth_type == "api_key":
            headers[self.auth.get("header", "X-API-Key")] = os.environ[self.auth["env_var"]]
        elif auth_type == "bearer_env":
            headers["Authorization"] = f"Bearer {os.environ[self.auth['env_var']]}"
        elif auth_type == "oauth2_client_credentials":
            headers["Authorization"] = f"Bearer {self._ensure_oauth_token()}"
        return headers

    def _ensure_oauth_token(self) -> str:
        import requests
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        resp = requests.post(
            os.environ[self.auth["token_url_env_var"]],
            data={
                "grant_type": "client_credentials",
                "client_id": os.environ[self.auth["client_id_env_var"]],
                "client_secret": os.environ[self.auth["client_secret_env_var"]],
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 3600)
        return self._token

    # ------------------------------------------------------------
    # Transporte
    # ------------------------------------------------------------
    def _call_jsonrpc(self, method: str, params: dict) -> Any:
        import requests
        self._rpc_id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._rpc_id}
        resp = requests.post(self.base_url, json=payload, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            err = body["error"]
            raise ConnectorError(f"[{self.name}] JSON-RPC error {err.get('code')}: {err.get('message')}")
        return body.get("result")

    def _call_rest(self, path: str, params: dict, http_method: str = "GET") -> Any:
        import requests
        url = f"{self.base_url}{path}"
        if http_method.upper() == "GET":
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        else:
            resp = requests.request(http_method, url, headers=self._headers(), json=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------
    # Interfaz pública (SourceConnector)
    # ------------------------------------------------------------
    def extract(self, entity: str, updated_since: str | None = None, **kwargs: Any) -> Iterator[dict]:
        entity_cfg = self.entities.get(entity)
        if not entity_cfg:
            raise ConnectorError(
                f"[{self.name}] Entidad '{entity}' no está definida en el config "
                f"(entidades disponibles: {list(self.entities)})"
            )

        pagination = entity_cfg.get("pagination")
        page_size = (pagination or {}).get("page_size", 100)
        offset = 0

        while True:
            params = dict(entity_cfg.get("params", {}))
            if updated_since:
                params["updated_since"] = updated_since
            if pagination:
                params["offset"] = offset
                params["limit"] = page_size

            if self.protocol == "jsonrpc":
                result = self._call_jsonrpc(entity_cfg["method"], params)
            else:
                result = self._call_rest(entity_cfg["path"], params, entity_cfg.get("http_method", "GET"))

            items = result.get("items", result) if isinstance(result, dict) else result
            if not items:
                break
            for item in items:
                yield item
            if not pagination or len(items) < page_size:
                break
            offset += page_size

    @classmethod
    def from_config_file(cls, path: str) -> "ApiConnector":
        import json
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))
