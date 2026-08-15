"""
Cliente REST/OAuth2 para Fracttal API.

Listo para usar en cuanto la clínica compre el plan con Integration API
habilitado. Mientras tanto, `demo_data_generator.py` implementa la MISMA
interfaz (get_activos, get_ordenes_trabajo, ...) devolviendo datos
sintéticos, así los DAGs de Airflow no cambian una línea al pasar de
demo -> producción: solo cambia una variable de entorno
(CMMS_USE_DEMO_DATA).

Referencia oficial: https://api.fracttal.com/reference
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests


@dataclass
class FracttalAuthConfig:
    token_url: str
    client_id: str
    client_secret: str


class FracttalClient:
    def __init__(self, base_url: str, auth: FracttalAuthConfig, requests_per_minute: int = 60):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._min_interval = 60.0 / max(requests_per_minute, 1)
        self._last_call_ts = 0.0

    # ---------------------------------------------------------------
    # Auth
    # ---------------------------------------------------------------
    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        resp = requests.post(
            self.auth.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.auth.client_id,
                "client_secret": self.auth.client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 3600)
        return self._token

    # ---------------------------------------------------------------
    # Rate limiting simple (cliente respeta el límite anunciado del plan)
    # ---------------------------------------------------------------
    def _throttle(self):
        elapsed = time.time() - self._last_call_ts
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_ts = time.time()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        self._throttle()
        token = self._ensure_token()
        resp = requests.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict[str, Any] | None = None, page_size: int = 100) -> Iterator[dict]:
        """
        NOTA: el esquema exacto de paginación (offset/limit vs cursor)
        debe confirmarse contra la doc real una vez haya credenciales.
        Este es un patrón genérico offset/limit razonable por defecto.
        """
        offset = 0
        params = dict(params or {})
        while True:
            params.update({"limit": page_size, "offset": offset})
            data = self._get(path, params)
            items = data.get("data", data.get("results", []))
            if not items:
                break
            for item in items:
                yield item
            if len(items) < page_size:
                break
            offset += page_size

    # ---------------------------------------------------------------
    # Interfaz pública — DEBE coincidir con demo_data_generator.py
    # ---------------------------------------------------------------
    def get_activos(self, updated_since: str | None = None) -> Iterator[dict]:
        params = {"updated_since": updated_since} if updated_since else {}
        yield from self._paginate("/v2/asset", params)

    def get_ordenes_trabajo(self, updated_since: str | None = None) -> Iterator[dict]:
        params = {"updated_since": updated_since} if updated_since else {}
        yield from self._paginate("/v2/workorder", params)

    def get_tareas(self, updated_since: str | None = None) -> Iterator[dict]:
        params = {"updated_since": updated_since} if updated_since else {}
        yield from self._paginate("/v2/task", params)

    def get_medidores(self) -> Iterator[dict]:
        yield from self._paginate("/v2/meter", {})

    def get_lecturas_medidor(self, medidor_id: str, desde: str, hasta: str) -> Iterator[dict]:
        yield from self._paginate(
            f"/v2/meter/{medidor_id}/readings", {"from": desde, "to": hasta}
        )

    def get_almacenes(self) -> Iterator[dict]:
        yield from self._paginate("/v2/warehouse", {})

    def get_recursos_humanos(self) -> Iterator[dict]:
        yield from self._paginate("/v2/hr", {})


def client_from_env() -> FracttalClient:
    return FracttalClient(
        base_url=os.environ.get("FRACTTAL_API_BASE_URL", "https://api.fracttal.com"),
        auth=FracttalAuthConfig(
            token_url=os.environ["FRACTTAL_TOKEN_URL"],
            client_id=os.environ["FRACTTAL_CLIENT_ID"],
            client_secret=os.environ["FRACTTAL_CLIENT_SECRET"],
        ),
        requests_per_minute=int(os.environ.get("FRACTTAL_RPM", "60")),
    )
