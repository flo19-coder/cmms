"""
Configuración sensible a entorno — primer paquete de
ESPECIFICACION_CMMS_CODEX.md (sección 18.5, punto 1: "rotar/eliminar
secretos predeterminados y separar desarrollo/producción") y criterio
de aceptación `AC-G06`: "Ningún ambiente productivo inicia con claves o
usuarios demo".

`CMMS_ENV` vale `development` (default, preserva el flujo local actual)
o `production`. En `production`, `require_secret()` EXIGE que la
variable de entorno pedida esté seteada explícitamente — no hay valor
por defecto débil. En `development` cae a un valor fijo cómodo.
"""
from __future__ import annotations

import os

CMMS_ENV = os.environ.get("CMMS_ENV", "development").strip().lower()
IS_PRODUCTION = CMMS_ENV == "production"


def require_secret(env_var: str, dev_default: str) -> str:
    value = os.environ.get(env_var)
    if IS_PRODUCTION:
        if not value:
            raise RuntimeError(
                f"CMMS_ENV=production requiere la variable de entorno '{env_var}' "
                "(sin valor por defecto permitido — ver ESPECIFICACION_CMMS_CODEX.md, AC-G06)."
            )
        return value
    return value or dev_default
