"""The PLM part library (Cascadia, PostgreSQL) -- read-only.

Connection settings come from backend/.env or the environment, never from code:
PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD (defaults: localhost, 5432, cascadia, postgres, postgres).
"""

import asyncio
import json
import os

from app.config import ENV_FILE, read_env_file

QUERY = ("SELECT item_number, name, attributes FROM items "
         "WHERE item_type IN ('Part', 'PhysicalPart') AND is_current = true")


class PlmError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def settings(env_file=None):
    values = {**read_env_file(env_file or ENV_FILE), **os.environ}
    return dict(host=values.get("PGHOST", "localhost"), port=values.get("PGPORT", "5432"),
                dbname=values.get("PGDATABASE", "cascadia"), user=values.get("PGUSER", "postgres"),
                password=values.get("PGPASSWORD", "postgres"), connect_timeout=5)


def _read(env_file=None):
    try:
        import psycopg2
    except ImportError as exc:
        raise PlmError("plm_driver_missing", "psycopg2 is not installed (run `uv sync` in backend/)") from exc
    try:
        conn = psycopg2.connect(**settings(env_file))
    except psycopg2.Error as exc:
        raise PlmError("plm_unavailable", "Cannot reach the PLM database: %s" % str(exc).strip()) from exc
    try:
        with conn, conn.cursor() as cur:
            cur.execute(QUERY)
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        raise PlmError("plm_query_failed", "PLM query failed: %s" % str(exc).strip()) from exc
    finally:
        conn.close()
    return [{"item_number": r[0], "name": r[1], "attributes": _as_dict(r[2])} for r in rows]


def _as_dict(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


async def load_parts(env_file=None):
    """All current parts: ``[{"item_number", "name", "attributes"}]``."""
    return await asyncio.to_thread(_read, env_file)
