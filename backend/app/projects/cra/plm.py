"""The PLM (Cascadia, PostgreSQL) -- read-only.

One record per current part, with everything the PLM knows about it:
name, description, material, weight, attributes and the attached CAD files
(including the bounding box Cascadia measured from the geometry).

Connection settings come from backend/.env or the environment, never from code:
PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD (defaults: localhost, 5432, cascadia, postgres, postgres).
"""

import asyncio
import json
import os
import re

from app.config import ENV_FILE, read_env_file

#: Everything known about a part; the joins are optional (an older schema falls back to BASIC)
FULL = """SELECT i.id, i.item_number, i.name, i.attributes,
                 p.description, p.material, p.weight, p.weight_unit, p.part_type
          FROM items i LEFT JOIN parts p ON p.item_id = i.id
          WHERE i.item_type = 'Part' AND i.is_current = true AND COALESCE(i.is_deleted, false) = false"""
BASIC = """SELECT id, item_number, name, attributes, NULL, NULL, NULL, NULL, NULL
           FROM items WHERE item_type IN ('Part', 'PhysicalPart') AND is_current = true"""
CAD = """SELECT item_id, file_name, storage_path, cad_metadata FROM vault_files
         WHERE file_category = 'cad_model' AND is_latest_version = true AND deleted_at IS NULL"""

TO_KG = {"kg": 1.0, "g": 0.001, "lb": 0.45359237, "lbs": 0.45359237, "oz": 0.028349523}


class PlmError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def settings(env_file=None):
    values = {**read_env_file(env_file or ENV_FILE), **os.environ}
    return dict(host=values.get("PGHOST", "localhost"), port=values.get("PGPORT", "5432"),
                dbname=values.get("PGDATABASE", "cascadia"), user=values.get("PGUSER", "postgres"),
                password=values.get("PGPASSWORD", "postgres"), connect_timeout=5)


def _as_dict(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extents(record):
    """Overall size of the part from its geometry, largest first (mm) -- or None.
    Source: the bounding box Cascadia measured from a CAD file, else a ``bboxMm`` attribute."""
    for f in record.get("cad") or []:
        box = f.get("bbox")
        if box:
            return sorted((round(v, 2) for v in box), reverse=True)
    raw = (record.get("attributes") or {}).get("bboxMm")
    if raw:
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", str(raw))]
        if len(nums) == 6:
            return sorted((round(abs(nums[i + 3] - nums[i]), 2) for i in range(3)), reverse=True)
    return None


def _record(row, cad):
    weight, unit = _num(row[6]), (row[7] or "kg").strip().lower()
    return {"id": str(row[0]), "item_number": row[1], "name": row[2] or "",
            "attributes": _as_dict(row[3]), "description": row[4] or "", "material": row[5] or "",
            "mass_kg": round(weight * TO_KG[unit], 4) if weight is not None and unit in TO_KG else None,
            "part_type": row[8] or "", "cad": cad.get(str(row[0]), []) if cad is not None else None}


def _cad_file(row):
    meta = _as_dict(row[3])
    box = meta.get("boundingBox") or {}
    bbox = [box[k] for k in ("x", "y", "z") if _num(box.get(k)) is not None]
    name = row[1] or ""
    return {"file": name, "format": name.rsplit(".", 1)[-1].lower() if "." in name else "",
            "path": row[2], "bbox": [float(v) for v in bbox] if len(bbox) == 3 else None}


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
        conn.autocommit = True                 # a failed optional query must not poison the next one
        with conn.cursor() as cur:
            try:
                cur.execute(FULL)
            except psycopg2.Error:
                cur.execute(BASIC)
            rows = cur.fetchall()
            try:
                cur.execute(CAD)
                cad = {}
                for r in cur.fetchall():
                    cad.setdefault(str(r[0]), []).append(_cad_file(r))
            except psycopg2.Error:
                cad = None                     # no vault in this PLM: "unknown", not "no CAD"
    except psycopg2.Error as exc:
        raise PlmError("plm_query_failed", "PLM query failed: %s" % str(exc).strip()) from exc
    finally:
        conn.close()
    return merge([_record(row, cad) for row in rows])


def merge(records):
    """One record per item number: the same part appears once per design/revision in Cascadia --
    its CAD files may hang on any of these rows."""
    merged = {}
    for rec in records:
        have = merged.get(rec["item_number"])
        if have is None:
            merged[rec["item_number"]] = {**rec, "attributes": dict(rec["attributes"]),
                                          "cad": None if rec["cad"] is None else list(rec["cad"])}
            continue
        for k in ("name", "description", "material", "mass_kg", "part_type"):
            if not have[k] and rec[k]:
                have[k] = rec[k]
        for k, v in rec["attributes"].items():
            have["attributes"].setdefault(k, v)
        if rec["cad"] is not None:
            have["cad"] = (have["cad"] or []) + [f for f in rec["cad"] if f not in (have["cad"] or [])]
    return list(merged.values())


async def load_parts(env_file=None):
    """All current parts as records (see module doc); ``cad`` is a list of files, [] or None (unknown)."""
    return await asyncio.to_thread(_read, env_file)
