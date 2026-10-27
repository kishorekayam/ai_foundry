"""Optional, read-only sampling of a few existing rows. Used only to give test cases values that are valid in the real
database (existing parent ids, existing unique values for duplicate tests). Nothing is written."""
from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from sqlalchemy import create_engine, text

from ..metadata.adapter import _connect_args
from ..targets import Target

SAMPLE_ROWS = 5


def _plain(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None
    if isinstance(v, (dict, list)):
        return v
    return v


def read_samples(target: Target, tables: list[str]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Returns ({table: rows}, notes). Failures are reported as notes: samples are an enhancement, never a requirement."""
    if target.db_type not in {"postgresql", "mysql"}:
        return {}, ["Row sampling is available for PostgreSQL and MySQL only."]
    out: dict[str, list[dict[str, Any]]] = {}
    notes: list[str] = []
    eng = create_engine(target.sqlalchemy_url(), connect_args=_connect_args(target))
    try:
        q = eng.dialect.identifier_preparer.quote
        with eng.connect() as conn:
            if target.db_type == "postgresql":
                conn.execute(text("SET TRANSACTION READ ONLY"))
            for t in tables:
                ref = f"{q(target.schema)}.{q(t)}" if target.db_type == "postgresql" else q(t)
                try:
                    rows = conn.execute(text(f"SELECT * FROM {ref} LIMIT {SAMPLE_ROWS}")).mappings().all()
                    out[t] = [{k: _plain(v) for k, v in r.items()} for r in rows]
                    if not rows:
                        notes.append(f"{t}: no existing rows, values from the collection were used.")
                except Exception as e:  # permissions, missing table ...
                    conn.rollback()
                    notes.append(f"{t}: could not read sample rows ({e.__class__.__name__}).")
    except Exception as e:
        notes.append(f"Could not read sample rows ({e.__class__.__name__}); values from the collection were used.")
    finally:
        eng.dispose()
    return out, notes
