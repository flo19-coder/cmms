"""
Tests del motor de transformación (transform/json_logic_engine.py) —
puros, sin dependencias externas, corren en cualquier entorno.

Ejecutar: python3 -m pytest transform/tests/ -v   (desde la raíz del repo)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from transform.json_logic_engine import apply_rule, transform_record


def test_var_simple():
    assert apply_rule({"var": "codigo"}, {"codigo": "EQ-001"}) == "EQ-001"


def test_var_anidado():
    assert apply_rule({"var": "a.b"}, {"a": {"b": 42}}) == 42


def test_var_inexistente_devuelve_none():
    assert apply_rule({"var": "no_existe"}, {}) is None


def test_trim():
    assert apply_rule({"trim": [{"var": "x"}]}, {"x": "  hola  "}) == "hola"


def test_upper_lower():
    assert apply_rule({"upper": [{"var": "x"}]}, {"x": "abc"}) == "ABC"
    assert apply_rule({"lower": [{"var": "x"}]}, {"x": "ABC"}) == "abc"


def test_concat():
    assert apply_rule({"concat": [{"var": "a"}, "-", {"var": "b"}]}, {"a": "X", "b": "Y"}) == "X-Y"


def test_split_path_y_path_level():
    data = {"p": "CLINICA/Sede_Lima/UCI"}
    assert apply_rule({"split_path": [{"var": "p"}]}, data) == ["CLINICA", "Sede_Lima", "UCI"]
    assert apply_rule({"path_level": [{"var": "p"}, 1]}, data) == "Sede_Lima"


def test_path_level_fuera_de_rango():
    assert apply_rule({"path_level": [{"var": "p"}, 10]}, {"p": "A/B"}) is None


def test_default_if_null():
    assert apply_rule({"default_if_null": [{"var": "x"}, 0]}, {"x": None}) == 0
    assert apply_rule({"default_if_null": [{"var": "x"}, 0]}, {"x": 5}) == 5


def test_map_lookup():
    mapping = {"A": "Alta", "B": "Baja"}
    assert apply_rule({"map_lookup": [{"var": "x"}, mapping]}, {"x": "A"}) == "Alta"
    assert apply_rule({"map_lookup": [{"var": "x"}, mapping, "Desconocido"]}, {"x": "Z"}) == "Desconocido"


def test_parse_date_valido_e_invalido():
    assert apply_rule({"parse_date": [{"var": "d"}]}, {"d": "2026-01-15"}) == "2026-01-15"
    assert apply_rule({"parse_date": [{"var": "d"}]}, {"d": "fecha-invalida"}) is None


def test_transform_record_mapeo_completo():
    raw = {"codigo": "EQ-001", "nombre": "  Chiller  ", "ubicacion_path": "A/B/C"}
    mapping = {
        "codigo_activo": {"var": "codigo"},
        "nombre_limpio": {"trim": [{"var": "nombre"}]},
        "sede": {"path_level": [{"var": "ubicacion_path"}, 1]},
    }
    result = transform_record(raw, mapping)
    assert result == {"codigo_activo": "EQ-001", "nombre_limpio": "Chiller", "sede": "B"}


def test_regla_con_mas_de_un_operador_falla():
    import pytest
    with pytest.raises(ValueError):
        apply_rule({"var": "a", "trim": "b"}, {})


# --- Operadores ampliados (texto) ---

def test_pad_left_pad_right():
    assert apply_rule({"pad_left": [{"var": "x"}, 5]}, {"x": "7"}) == "00007"
    assert apply_rule({"pad_right": [{"var": "x"}, 5, "-"]}, {"x": "7"}) == "7----"


def test_replace():
    assert apply_rule({"replace": [{"var": "x"}, "-", "_"]}, {"x": "EQ-001"}) == "EQ_001"


def test_regex_replace():
    assert apply_rule({"regex_replace": ["[0-9]+", {"var": "x"}, "#"]}, {"x": "EQ-001"}) == "EQ-#"


def test_slice():
    assert apply_rule({"slice": [{"var": "x"}, 0, 2]}, {"x": "EQ-001"}) == "EQ"
    assert apply_rule({"slice": [{"var": "x"}, 3]}, {"x": "EQ-001"}) == "001"


# --- Operadores ampliados (números) ---

def test_round_to():
    assert apply_rule({"round_to": [{"var": "x"}, 2]}, {"x": 3.14159}) == 3.14


def test_clamp():
    assert apply_rule({"clamp": [{"var": "x"}, 0, 10]}, {"x": 15}) == 10
    assert apply_rule({"clamp": [{"var": "x"}, 0, 10]}, {"x": -5}) == 0


def test_to_number():
    assert apply_rule({"to_number": [{"var": "x"}]}, {"x": "3.5"}) == 3.5
    assert apply_rule({"to_number": [{"var": "x"}]}, {"x": "no-numero"}) is None


# --- Operadores ampliados (fechas) ---

def test_add_days():
    assert apply_rule({"add_days": [{"var": "d"}, 5]}, {"d": "2026-01-01"}) == "2026-01-06T00:00:00"


def test_format_date():
    assert apply_rule({"format_date": [{"var": "d"}, "%d/%m/%Y"]}, {"d": "2026-01-15"}) == "15/01/2026"


def test_weekday_name():
    assert apply_rule({"weekday_name": [{"var": "d"}]}, {"d": "2026-01-01"}) == "jueves"


# --- Operadores ampliados (listas) ---

def test_join():
    assert apply_rule({"join": [{"var": "x"}, ", "]}, {"x": ["a", "b", "c"]}) == "a, b, c"


def test_sum_list():
    assert apply_rule({"sum_list": [{"var": "x"}]}, {"x": [1, 2, 3.5]}) == 6.5


def test_distinct():
    assert apply_rule({"distinct": [{"var": "x"}]}, {"x": [1, 2, 2, 3, 1]}) == [1, 2, 3]


def test_first_last_count():
    data = {"x": [10, 20, 30]}
    assert apply_rule({"first": [{"var": "x"}]}, data) == 10
    assert apply_rule({"last": [{"var": "x"}]}, data) == 30
    assert apply_rule({"count_list": [{"var": "x"}]}, data) == 3


# --- Operadores ampliados (utilidad) ---

def test_coalesce():
    assert apply_rule({"coalesce": [{"var": "a"}, {"var": "b"}, "default"]}, {"a": None, "b": "valor"}) == "valor"
    assert apply_rule({"coalesce": [{"var": "a"}, {"var": "b"}]}, {"a": None, "b": None}) is None


def test_is_empty():
    assert apply_rule({"is_empty": [{"var": "x"}]}, {"x": ""}) is True
    assert apply_rule({"is_empty": [{"var": "x"}]}, {"x": "algo"}) is False


def test_to_string():
    assert apply_rule({"to_string": [{"var": "x"}]}, {"x": 42}) == "42"


def test_to_bool():
    assert apply_rule({"to_bool": [{"var": "x"}]}, {"x": "si"}) is True
    assert apply_rule({"to_bool": [{"var": "x"}]}, {"x": "no"}) is False
    assert apply_rule({"to_bool": [{"var": "x"}]}, {"x": 0}) is False
