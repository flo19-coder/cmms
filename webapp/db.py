"""
Capa de acceso a datos — compartida entre las vistas HTML (app.py) y la
API REST (api.py). Centralizar acá evita 2 implementaciones divergentes
de las mismas consultas cuando se agregue la interfaz definitiva.
"""
from __future__ import annotations

import datetime as dt
import decimal
import logging
import os
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger("cmms.db")

DB_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}

# Pool de conexiones — evita abrir/cerrar una conexión TCP por cada
# request, que es lo que hacía la versión anterior. minconn=1 para no
# gastar recursos en reposo, maxconn=10 alcanza sobrado para uso de
# kiosco/QR de una sola clínica en un servidor local.
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **DB_PARAMS)
    return _pool


@contextmanager
def get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


class DatabaseError(Exception):
    """Envuelve errores de Postgres con un mensaje seguro para exponer en la API."""


def _normalize_value(v):
    """
    Decimal -> float, para que la API REST devuelva números como número
    JSON real (no string). Las fechas se dejan como date/datetime nativos
    porque los templates HTML usan .strftime() sobre ellas — Flask ya
    las serializa a texto automáticamente al pasar por jsonify().
    """
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def _normalize_row(row: dict) -> dict:
    return {k: _normalize_value(v) for k, v in row.items()}


def query(sql: str, params: tuple = ()) -> list[dict]:
    t0 = time.monotonic()
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [_normalize_row(dict(r)) for r in rows]
    except psycopg2.Error as e:
        logger.error("Error de consulta (%.3fs): %s | SQL=%s", time.monotonic() - t0, e, sql[:200])
        raise DatabaseError("No se pudo completar la consulta a la base de datos.") from e
    finally:
        elapsed = time.monotonic() - t0
        if elapsed > 0.5:
            logger.warning("Consulta lenta (%.3fs): %s", elapsed, sql[:200])


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    """
    Para INSERT/UPDATE/DELETE — a diferencia de query(), NO intenta
    fetchall() (esas sentencias no devuelven filas) y SÍ hace commit()
    explícito (las conexiones del pool no están en autocommit).
    Devuelve la cantidad de filas afectadas.
    """
    t0 = time.monotonic()
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                affected = cur.rowcount
            conn.commit()
            return affected
    except psycopg2.Error as e:
        logger.error("Error de escritura (%.3fs): %s | SQL=%s", time.monotonic() - t0, e, sql[:200])
        raise DatabaseError("No se pudo completar la operación en la base de datos.") from e


class TransactionError(DatabaseError):
    """Una operación transaccional falló — se hizo rollback de TODO."""


@contextmanager
def transaction():
    """
    Uso:
        with db.transaction() as cur:
            cur.execute("UPDATE ...")
            cur.execute("INSERT ...")
        # si algo dentro del bloque lanza excepción, se hace ROLLBACK
        # completo -- ninguna de las sentencias queda aplicada.

    Esto es lo que hace que "finalizar una OT con repuestos" sea
    realmente transaccional: actualizar el estado de la OT, registrar
    los repuestos usados, y descontar stock del almacén son 3
    sentencias que deben aplicarse las 3 juntas o ninguna.
    """
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            conn.commit()
        except Exception as e:
            conn.rollback()
            if isinstance(e, psycopg2.Error):
                logger.error("Transacción revertida (rollback): %s", e)
                raise TransactionError(f"La operación falló y se revirtió: {e}") from e
            logger.error("Transacción revertida (rollback) por error de negocio: %s", e)
            raise
        finally:
            cur.close()


def health_check() -> bool:
    try:
        query_one("SELECT 1 AS ok")
        return True
    except DatabaseError:
        return False
