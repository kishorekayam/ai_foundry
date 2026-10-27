"""Python database adapter for approved loads: parameterized inserts, parents first, in batches, then verification."""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy import Boolean, Date, DateTime, MetaData, Numeric, Table, create_engine, func, select, text
from sqlalchemy import Integer as SAInteger

from . import boomi_client, registry, store
from .models import LoadJob, LoadStep, LoadTableResult, Verification
from .targets import Target, get_target

log = logging.getLogger("atom.loader")
BATCH = 500


def new_steps(boomi: bool) -> list[LoadStep]:
    note = None if boomi else "Boomi not configured, executed directly by the Python adapter"
    return [
        LoadStep(id="confirm", layer="React", label="Load approved by user", state="done"),
        LoadStep(id="job", layer="FastAPI", label="Create load job, check target against approved list"),
        LoadStep(id="recv", layer="Boomi", label="Web Services Server receives approved request", detail=note),
        LoadStep(id="batch", layer="Boomi", label="Retrieve batch reference for the job", detail=note),
        LoadStep(id="adapter", layer="Boomi", label="Choose load adapter (MVP: Python database adapter)", detail=note),
        LoadStep(id="insert", layer="Database", label="Insert parents first, in batches"),
        LoadStep(id="status", layer="Boomi", label="Try/Catch then return batch status", detail=note),
        LoadStep(id="verify", layer="FastAPI", label="Verify counts and foreign keys"),
    ]


def set_step(load: LoadJob, step_id: str, state: str, detail: str | None = None) -> None:
    for i, s in enumerate(load.steps):
        if s.id == step_id:
            load.steps[i] = s.model_copy(update={"state": state, "detail": detail if detail is not None else s.detail})


def _coerce(col_type: Any, v: Any) -> Any:
    if v is None:
        return None
    from sqlalchemy import JSON, Interval, LargeBinary, Time, Uuid

    if isinstance(col_type, Uuid) and isinstance(v, str):
        return uuid.UUID(v)
    if isinstance(col_type, JSON) and isinstance(v, str):
        return json.loads(v)
    if isinstance(col_type, LargeBinary) and isinstance(v, str):
        return bytes.fromhex(v[2:] if v.startswith("\\x") else v)
    if isinstance(col_type, Time) and isinstance(v, str):
        return time.fromisoformat(v)
    if isinstance(col_type, Interval) and isinstance(v, str):
        m = re.match(r"(\d+)\s*minutes?", v)
        return timedelta(minutes=int(m.group(1))) if m else timedelta(0)
    if isinstance(col_type, DateTime) and isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    if isinstance(col_type, Date) and not isinstance(col_type, DateTime) and isinstance(v, str):
        return date.fromisoformat(v[:10])
    if isinstance(col_type, Numeric) and not isinstance(v, Decimal):
        return Decimal(str(v))
    return v


def _pg_text(v: Any) -> Any:
    """Render a Python value as PostgreSQL text input so it can be CAST to the column type."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "{" + ",".join("NULL" if x is None else '"' + str(_pg_text(x)).replace("\\", "\\\\").replace('"', '\\"') + '"' for x in v) + "}"
    if isinstance(v, dict):
        return json.dumps(v)
    if isinstance(v, (bytes, bytearray)):
        return "\\x" + bytes(v).hex()
    if isinstance(v, timedelta):
        return f"{int(v.total_seconds())} seconds"
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    return str(v)


def _insert_overriding(conn: Any, eng: Any, tbl: Table, rows: list[dict[str, Any]]) -> None:
    """INSERT ... OVERRIDING SYSTEM VALUE for GENERATED ALWAYS identity columns (explicit keys keep foreign keys valid)."""
    q = eng.dialect.identifier_preparer.quote
    cols = [c for c in tbl.columns if c.name in rows[0]]
    marks = ", ".join(f"CAST(:p{i} AS {c.type.compile(dialect=eng.dialect)})" for i, c in enumerate(cols))
    ref = f"{q(tbl.schema)}.{q(tbl.name)}" if tbl.schema else q(tbl.name)
    sql = f"INSERT INTO {ref} ({', '.join(q(c.name) for c in cols)}) OVERRIDING SYSTEM VALUE VALUES ({marks})"
    conn.execute(text(sql), [{f"p{i}": _pg_text(r.get(c.name)) for i, c in enumerate(cols)} for r in rows])


_STATE: dict[str, list[tuple[str, list[dict[str, Any]]]]] = {}  # load id -> rows that really went into the database
SKIPPABLE = {"23505", "23503"}  # unique_violation / foreign_key_violation: a row that clashes with existing data


def _sqlstate(e: Exception) -> Optional[str]:
    orig = getattr(e, "orig", None) or e.__cause__ or e
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _insert_rows(conn: Any, eng: Any, tbl: Table, rows: list[dict[str, Any]], override: bool) -> None:
    if override:
        _insert_overriding(conn, eng, tbl, rows)
    else:
        conn.execute(tbl.insert(), rows)


def prepare_keys(eng: Any, target: Target, meta: MetaData, tables: list[tuple[str, list[dict[str, Any]]]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Serial / identity primary keys are re-allocated from the target's own sequences, so generated ids can never clash
    with rows that are already in the table. Foreign keys that point at a re-keyed parent are rewritten to match."""
    if target.db_type != "postgresql":
        return tables
    keymap: dict[tuple[str, str], dict[Any, Any]] = {}
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for name, rows in tables:
        tbl = Table(name, meta, autoload_with=eng, schema=_schema(target))
        pk = list(tbl.primary_key.columns)
        new_rows = [dict(r) for r in rows]
        if len(pk) == 1 and isinstance(pk[0].type, SAInteger) and rows:
            with eng.begin() as conn:
                seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f'"{target.schema}"."{name}"', "c": pk[0].name}).scalar()
                if seq:
                    ids = [r[0] for r in conn.execute(text("SELECT nextval(CAST(:s AS regclass)) FROM generate_series(1, :n)"), {"s": seq, "n": len(rows)})]
                    keymap[(name, pk[0].name)] = {r[pk[0].name]: new for r, new in zip(rows, sorted(ids))}
        for fk in tbl.foreign_keys:  # rewrite references to re-keyed parents (incl. self references)
            km = keymap.get((fk.column.table.name, fk.column.name))
            if km:
                for r in new_rows:
                    v = r.get(fk.parent.name)
                    if v is not None and v in km:
                        r[fk.parent.name] = km[v]
        km = keymap.get((name, pk[0].name)) if len(pk) == 1 else None
        if km:
            for r in new_rows:
                r[pk[0].name] = km[r[pk[0].name]]
        out.append((name, new_rows))
    return out


def execute_load(load: LoadJob, tables: list[tuple[str, list[dict[str, Any]]]], target: Target, on_progress: Callable[[], None], identity_always: Optional[dict[str, set[str]]] = None, ref_cols: Optional[dict[str, set[str]]] = None) -> dict[str, Any]:
    """Insert `tables` (parents first). Rows that clash with data already in the database are skipped and reported, and rows
    whose parent was skipped are skipped with it; anything else (type, not-null, check errors) fails the load."""
    identity_always = identity_always or {}
    ref_cols = ref_cols or {}
    eng = create_engine(target.sqlalchemy_url(), connect_args={"connect_timeout": 10})
    meta = MetaData()
    results: list[dict[str, Any]] = []
    inserted: list[tuple[str, list[dict[str, Any]]]] = []
    skipped_vals: dict[tuple[str, str], set[Any]] = {}
    try:
        tables = prepare_keys(eng, target, meta, tables)
        for name, rows in tables:
            res = next(p for p in load.per_table if p.table == name)
            try:
                tbl = Table(name, meta, autoload_with=eng, schema=_schema(target))
            except Exception as e:
                res.failed_batches += 1
                results.append({"table": name, "inserted": 0, "failedBatches": 1, "error": f"Table not found in target: {e.__class__.__name__}"})
                on_progress()
                break
            override = target.db_type == "postgresql" and any(c.name in identity_always.get(name, set()) for c in tbl.columns)
            prepared: list[dict[str, Any]] = []
            originals: list[dict[str, Any]] = []
            cascade = 0
            for r in rows:
                if any(r.get(fk.parent.name) in skipped_vals.get((fk.column.table.name, fk.column.name), ()) for fk in tbl.foreign_keys if r.get(fk.parent.name) is not None):
                    cascade += 1  # its parent record was skipped: skip it too and remember its keys for its own children
                    for col in ref_cols.get(name, ()):
                        if r.get(col) is not None:
                            skipped_vals.setdefault((name, col), set()).add(r[col])
                    continue
                originals.append(r)
                prepared.append({k: _coerce(tbl.c[k].type, v) for k, v in r.items() if k in tbl.c})
            skipped_rows = cascade
            ok_rows: list[dict[str, Any]] = []
            failed = False
            for i in range(0, len(prepared), BATCH):
                chunk, orig = prepared[i : i + BATCH], originals[i : i + BATCH]
                try:
                    with eng.begin() as conn:
                        _insert_rows(conn, eng, tbl, chunk, override)
                    ok_rows.extend(orig)
                except Exception as e:
                    if _sqlstate(e) not in SKIPPABLE:
                        res.failed_batches += 1
                        failed = True
                        load.error = f"{name}: {str(e.__cause__ or e).splitlines()[0][:200]}"
                        break
                    # the chunk clashes with existing rows: retry row by row and skip only the clashing ones
                    try:
                        with eng.begin() as conn:
                            for row, o in zip(chunk, orig):
                                try:
                                    with conn.begin_nested():
                                        _insert_rows(conn, eng, tbl, [row], override)
                                    ok_rows.append(o)
                                except Exception as e2:
                                    if _sqlstate(e2) not in SKIPPABLE:
                                        raise
                                    skipped_rows += 1
                                    for col in ref_cols.get(name, ()):
                                        if o.get(col) is not None:
                                            skipped_vals.setdefault((name, col), set()).add(o[col])
                    except Exception as e3:
                        res.failed_batches += 1
                        failed = True
                        load.error = f"{name}: {str(e3.__cause__ or e3).splitlines()[0][:200]}"
                        break
                on_progress()
            res.inserted += len(ok_rows)
            res.skipped += skipped_rows
            if skipped_rows:
                load.warnings.append(f"{name}: {skipped_rows} record(s) skipped because they clash with rows already in your database (or depend on a skipped record).")
            inserted.append((name, ok_rows))
            results.append({"table": name, "inserted": res.inserted, "failedBatches": res.failed_batches, "skipped": res.skipped})
            if failed:
                break
            if target.db_type == "postgresql":  # keep serial sequences ahead of explicitly inserted keys
                for c in tbl.primary_key.columns:
                    if isinstance(c.type, SAInteger):
                        with eng.begin() as conn:
                            if _has_seq(conn, target, name, c.name):
                                conn.execute(text(f'SELECT setval(pg_get_serial_sequence(:t, :c), GREATEST((SELECT COALESCE(MAX("{c.name}"), 1) FROM "{target.schema}"."{name}"), (SELECT last_value FROM {_seq_name(conn, target, name, c.name)})))'), {"t": f'"{target.schema}"."{name}"', "c": c.name})
        return {"perTable": results, "inserted": inserted, "status": "COMPLETE" if not any(r["failedBatches"] for r in results) and len(results) == len(tables) else "ERROR"}
    finally:
        eng.dispose()


def _seq_name(conn: Any, target: Target, table: str, col: str) -> str:
    return conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f'"{target.schema}"."{table}"', "c": col}).scalar()


def _has_seq(conn: Any, target: Target, table: str, col: str) -> bool:
    return conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f'"{target.schema}"."{table}"', "c": col}).scalar() is not None


def _schema(target: Target) -> str | None:
    return target.schema if target.db_type == "postgresql" else None


def verify_load(target: Target, schema_tables: dict[str, Any], tables: list[tuple[str, list[dict[str, Any]]]], inserted: Optional[dict[str, int]] = None) -> Verification:
    """Counts of the exact generated keys that now exist, and foreign keys of those rows. Reads no other data.
    Works for single, composite or missing primary keys (tables without one fall back to the insert counts)."""
    from sqlalchemy import tuple_

    inserted = inserted or {}
    eng = create_engine(target.sqlalchemy_url(), connect_args={"connect_timeout": 10})
    meta = MetaData()
    counts_ok, fk_ok = True, True
    try:
        for name, rows in tables:
            tbl = Table(name, meta, autoload_with=eng, schema=_schema(target))
            pk = list(tbl.primary_key.columns)
            if not pk:  # nothing identifies our rows: trust the adapter's per-batch counts
                if inserted.get(name, len(rows)) != len(rows):
                    counts_ok = False
                continue
            keys = [tuple(_coerce(c.type, r[c.name]) for c in pk) for r in rows]
            where = (lambda chunk: pk[0].in_([k[0] for k in chunk])) if len(pk) == 1 else (lambda chunk: tuple_(*pk).in_(chunk))
            found = 0
            with eng.connect() as conn:
                for i in range(0, len(keys), 1000):
                    found += conn.execute(select(func.count()).select_from(tbl).where(where(keys[i : i + 1000]))).scalar_one()
                if found != len(keys):
                    counts_ok = False
                for fk in tbl.foreign_keys:
                    parent = fk.column.table
                    parent_col = fk.column
                    if parent is tbl:  # self-referencing FK: join the table to an alias of itself
                        parent = tbl.alias("parent_row")
                        parent_col = parent.c[fk.column.name]
                    child_col = fk.parent
                    for i in range(0, len(keys), 1000):
                        bad = conn.execute(
                            select(func.count()).select_from(tbl.outerjoin(parent, child_col == parent_col))
                            .where(where(keys[i : i + 1000])).where(child_col.is_not(None)).where(parent_col.is_(None))
                        ).scalar_one()
                        if bad:
                            fk_ok = False
        return Verification(counts_match=counts_ok, fk_valid=fk_ok)
    finally:
        eng.dispose()


def run_direct(load_id: str, job_id: str, target_id: str) -> None:
    """Used when Boomi is not configured: same steps, executed by the Python adapter."""
    load = store.get_load(load_id)
    assert load
    try:
        for s in ("job", "recv", "batch", "adapter"):
            set_step(load, s, "done")
        run_adapter(load, job_id, target_id)
        set_step(load, "status", "done")
        finish(load, job_id, target_id)
    except Exception as e:
        fail(load, str(e))


def batch_for(job_id: str) -> tuple[Any, list[tuple[str, list[dict[str, Any]]]]]:
    st = store.get_job(job_id)
    if not st:
        raise KeyError("Unknown job")
    return st, [(t, st.dataset[t]) for t in st.order if st.dataset.get(t)]


def run_adapter(load: LoadJob, job_id: str, target_id: str) -> dict[str, Any]:
    target = get_target(target_id)
    if not target or not target.load_allowed:
        raise PermissionError("Direct load is only enabled for approved PostgreSQL test targets.")
    _, tables = batch_for(job_id)
    set_step(load, "insert", "running")
    st, _ = batch_for(job_id)
    ident = {t.name: {c.name for c in t.columns if c.identity_always} for t in st.schema.tables}
    refs: dict[str, set[str]] = {}
    for t in st.schema.tables:
        for f in t.foreign_keys:
            refs.setdefault(f.ref_table, set()).add(f.ref_column)
    result = execute_load(load, tables, target, on_progress=lambda: None, identity_always=ident, ref_cols=refs)
    _STATE[load.id] = result.pop("inserted")
    set_step(load, "insert", "done" if result["status"] == "COMPLETE" else "failed", load.error)
    return result


def finish(load: LoadJob, job_id: str, target_id: str) -> None:
    target = get_target(target_id)
    assert target
    set_step(load, "verify", "running")
    st, tables = batch_for(job_id)
    tables = _STATE.pop(load.id, None) or tables  # verify exactly the rows that were written (keys may have been re-allocated)
    v = verify_load(target, {}, tables, {p.table: p.inserted for p in load.per_table})
    load.verification = v
    ok = v.counts_match and v.fk_valid and not any(p.failed_batches for p in load.per_table)
    load.boomi_status = "COMPLETE" if ok else "ERROR"
    load.status = "success" if ok else "failed"
    set_step(load, "verify", "done" if ok else "failed", None if ok else (load.error or "Counts or foreign keys did not match"))
    registry.audit(load.id, "load", "SUCCESS" if ok else "FAILED", f"job {job_id}: counts_match={v.counts_match} fk_valid={v.fk_valid}", target_id)


def fail(load: LoadJob, msg: str) -> None:
    log.warning("load %s failed: %s", load.id, msg)
    load.status = "failed"
    load.boomi_status = "ERROR"
    load.error = msg
    for s in load.steps:
        if s.state == "running":
            set_step(load, s.id, "failed", msg)


def start_load(load_id: str, job_id: str, target_id: str, plan_tables: list[tuple[str, int]]) -> LoadJob:
    boomi = boomi_client.configured()
    load = LoadJob(id=load_id, steps=new_steps(boomi), per_table=[LoadTableResult(table=t, expected=n) for t, n in plan_tables])
    registry.audit(load_id, "load", "REQUESTED", f"job {job_id}, via {'Boomi Process B' if boomi else 'direct Python adapter'}", target_id)
    set_step(load, "job", "done")
    store.put_load(load)
    if boomi:
        threading.Thread(target=_via_boomi, args=(load, job_id, target_id), daemon=True).start()
        set_step(load, "recv", "running")
    else:
        threading.Thread(target=run_direct, args=(load_id, job_id, target_id), daemon=True).start()
    return load


def _via_boomi(load: LoadJob, job_id: str, target_id: str) -> None:
    try:
        resp = boomi_client.run_load_process(load.id, job_id, target_id)
        set_step(load, "status", "done", f"Boomi status: {resp.get('status', 'unknown')}")
        if resp.get("status") not in ("COMPLETE", "SUCCESS"):
            raise RuntimeError(f"Boomi reported {resp.get('status')}: {resp.get('error', load.error or 'load failed')}")
        finish(load, job_id, target_id)
    except Exception as e:
        fail(load, str(e))
