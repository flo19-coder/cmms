"""
Motor de transformación basado en JSON Logic + operadores custom del
proyecto. Envuelve `json_logic` (implementación estándar, ~20 operadores:
==, !=, <, >, and, or, if, +, -, *, /, %, in, cat, substr, map, filter,
reduce, all, none, some, merge, missing...) y agrega operadores propios
(catálogo abajo) necesarios para mapear el modelo de cualquier fuente al
esquema `core.*` de Postgres — juntos suman 40+ operadores disponibles
en cualquier `mapping` de `transform/config/*.json`.

Catálogo de operadores CUSTOM (además de los estándar de json_logic):
  Texto:     concat, trim, upper, lower, pad_left, pad_right, replace,
             regex_extract, regex_replace, slice
  Números:   round_to, clamp, to_number
  Fechas:    parse_date, date_diff_days, now, add_days, format_date,
             weekday_name
  Listas:    join, sum_list, distinct, first, last, count_list
  Rutas:     split_path, path_level
  Utilidad:  default_if_null, map_lookup, coalesce, is_empty, to_string,
             to_bool

Instalar: pip install json-logic-qubit   (o json-logic-py, ver requirements.txt)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable

# ---------------------------------------------------------------------
# Registro de operadores custom (más allá de los estándar de JSON Logic:
# ==, !=, <, >, and, or, if, +, -, *, /, var, map, filter, etc.)
# ---------------------------------------------------------------------
CUSTOM_OPERATORS: dict[str, Callable] = {}


def operator(name: str):
    def deco(fn: Callable):
        CUSTOM_OPERATORS[name] = fn
        return fn
    return deco


@operator("concat")
def _concat(*args) -> str:
    return "".join(str(a) for a in args if a is not None)


@operator("trim")
def _trim(s: str) -> str:
    return (s or "").strip()


@operator("upper")
def _upper(s: str) -> str:
    return (s or "").upper()


@operator("lower")
def _lower(s: str) -> str:
    return (s or "").lower()


@operator("regex_extract")
def _regex_extract(pattern: str, s: str, group: int = 0) -> str | None:
    m = re.search(pattern, s or "")
    return m.group(group) if m else None


@operator("split_path")
def _split_path(path: str, sep: str = "/") -> list[str]:
    """Descompone 'CLINICA_INTL/Sede_Lima/UCI_Adultos' en niveles."""
    return [p for p in (path or "").split(sep) if p]


@operator("path_level")
def _path_level(path: str, level: int, sep: str = "/") -> str | None:
    parts = _split_path(path, sep)
    return parts[level] if 0 <= level < len(parts) else None


@operator("parse_date")
def _parse_date(s: str, fmt: str = "%Y-%m-%d") -> str | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, fmt).date().isoformat()
    except ValueError:
        return None


@operator("date_diff_days")
def _date_diff_days(d1: str, d2: str) -> int | None:
    if not d1 or not d2:
        return None
    a = datetime.fromisoformat(d1)
    b = datetime.fromisoformat(d2)
    return (a - b).days


@operator("default_if_null")
def _default_if_null(value: Any, default: Any) -> Any:
    return default if value is None else value


@operator("map_lookup")
def _map_lookup(value: Any, mapping: dict, default: Any = None) -> Any:
    return mapping.get(value, default)


# ---------------------------------------------------------------------
# Texto (ampliación)
# ---------------------------------------------------------------------
@operator("pad_left")
def _pad_left(s: Any, length: int, char: str = "0") -> str:
    return str(s if s is not None else "").rjust(int(length), char)


@operator("pad_right")
def _pad_right(s: Any, length: int, char: str = " ") -> str:
    return str(s if s is not None else "").ljust(int(length), char)


@operator("replace")
def _replace(s: Any, old: str, new: str) -> str:
    return str(s if s is not None else "").replace(old, new)


@operator("regex_replace")
def _regex_replace(pattern: str, s: Any, replacement: str = "") -> str:
    return re.sub(pattern, replacement, str(s if s is not None else ""))


@operator("slice")
def _slice(s: Any, start: int, end: int | None = None) -> str:
    s = str(s if s is not None else "")
    return s[start:end] if end is not None else s[start:]


# ---------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------
@operator("round_to")
def _round_to(value: Any, decimals: int = 0) -> float | None:
    if value is None:
        return None
    return round(float(value), int(decimals))


@operator("clamp")
def _clamp(value: Any, min_val: float, max_val: float) -> float | None:
    if value is None:
        return None
    return max(float(min_val), min(float(max_val), float(value)))


@operator("to_number")
def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# Fechas (ampliación)
# ---------------------------------------------------------------------
_DIAS_SEMANA_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@operator("now")
def _now(*_args) -> str:
    return datetime.now().isoformat()


@operator("add_days")
def _add_days(date_str: str, days: int) -> str | None:
    if not date_str:
        return None
    d = datetime.fromisoformat(date_str)
    return (d + timedelta(days=int(days))).isoformat()


@operator("format_date")
def _format_date(date_str: str, fmt: str = "%Y-%m-%d") -> str | None:
    if not date_str:
        return None
    return datetime.fromisoformat(date_str).strftime(fmt)


@operator("weekday_name")
def _weekday_name(date_str: str) -> str | None:
    if not date_str:
        return None
    return _DIAS_SEMANA_ES[datetime.fromisoformat(date_str).weekday()]


# ---------------------------------------------------------------------
# Listas
# ---------------------------------------------------------------------
@operator("join")
def _join(items: Any, sep: str = ", ") -> str:
    return sep.join(str(i) for i in (items or []))


@operator("sum_list")
def _sum_list(items: Any) -> float:
    return sum(float(i) for i in (items or []) if i is not None)


@operator("distinct")
def _distinct(items: Any) -> list:
    seen, out = set(), []
    for i in items or []:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


@operator("first")
def _first(items: Any) -> Any:
    return items[0] if items else None


@operator("last")
def _last(items: Any) -> Any:
    return items[-1] if items else None


@operator("count_list")
def _count_list(items: Any) -> int:
    return len(items) if items else 0


# ---------------------------------------------------------------------
# Utilidad
# ---------------------------------------------------------------------
@operator("coalesce")
def _coalesce(*args) -> Any:
    for a in args:
        if a is not None and a != "":
            return a
    return None


@operator("is_empty")
def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


@operator("to_string")
def _to_string(value: Any) -> str | None:
    return None if value is None else str(value)


@operator("to_bool")
def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("true", "1", "si", "sí", "yes", "y")


# ---------------------------------------------------------------------
# Evaluador simple (aplica operadores custom; delega el resto a json_logic)
# ---------------------------------------------------------------------
def apply_rule(rule: dict | Any, data: dict) -> Any:
    """
    Evalúa una regla estilo JSON Logic. Si el operador es uno de los
    custom definidos arriba, lo resuelve directamente; si no, intenta
    usar la librería estándar `json_logic` como fallback.
    """
    if not isinstance(rule, dict):
        return rule

    if len(rule) != 1:
        raise ValueError(f"Regla JSON Logic inválida (debe tener 1 operador raíz): {rule}")

    op, raw_args = next(iter(rule.items()))
    args = raw_args if isinstance(raw_args, list) else [raw_args]

    # map_lookup es especial: su 2do/3er argumento son valores LITERALES
    # (el diccionario de mapeo y el default), no reglas anidadas — no hay
    # que re-evaluarlos con apply_rule() aunque sean dicts.
    if op == "map_lookup":
        resolved_first = apply_rule(args[0], data) if isinstance(args[0], dict) else args[0]
        rest = args[1:]
        return CUSTOM_OPERATORS["map_lookup"](resolved_first, *rest)

    resolved_args = [apply_rule(a, data) if isinstance(a, dict) else a for a in args]

    if op == "var":
        path = resolved_args[0]
        cur = data
        for part in str(path).split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    if op in CUSTOM_OPERATORS:
        return CUSTOM_OPERATORS[op](*resolved_args)

    # Fallback a librería estándar para operadores comunes (==, and, if, etc.)
    try:
        from json_logic import jsonLogic
        return jsonLogic(rule, data)
    except ImportError as e:
        raise RuntimeError(
            "Operador no reconocido y librería 'json_logic' no instalada. "
            "pip install json-logic-qubit"
        ) from e


def transform_record(record: dict, mapping_config: dict) -> dict:
    """
    Aplica un config de mapeo campo->regla sobre un registro crudo.

    mapping_config ejemplo:
    {
      "codigo_activo": {"var": "codigo"},
      "nivel_2_sede": {"path_level": [{"var": "ubicacion_path"}, 1]},
      "nombre_upper": {"upper": [{"var": "nombre"}]}
    }
    """
    return {field: apply_rule(rule, record) for field, rule in mapping_config.items()}


if __name__ == "__main__":
    demo_record = {
        "codigo": "EQ-0001",
        "nombre": "  Ventilador Mecánico 001  ",
        "ubicacion_path": "CLINICA_INTL/Sede_Lima/UCI_Adultos",
    }
    demo_mapping = {
        "codigo_activo": {"var": "codigo"},
        "nombre_limpio": {"trim": [{"var": "nombre"}]},
        "sede": {"path_level": [{"var": "ubicacion_path"}, 1]},
        "servicio": {"path_level": [{"var": "ubicacion_path"}, 2]},
    }
    print(transform_record(demo_record, demo_mapping))
