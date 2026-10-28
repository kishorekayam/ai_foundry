# app/engine/repair.py
"""Self-healing pass: after generation every rule that can be derived from the metadata is re-checked and, where a
value breaks it, repaired. Rows that cannot be made valid are removed and reported, so the final dataset never
contains a violation. Works from the discovered schema only (no table or column names are known here)."""
from __future__ import annotations

from typing import Any, Optional

from ..models import Column, Schema, Table
from .generator import GenContext, Row, is_date, is_int, is_num, parse_range
from .validator import _type_ok


def _clamp(c: Column, v: Any) -> Any:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not c.check:
        return v
    lo, hi = parse_range(c.check)
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return int(v) if is_int(c.type) else v


def _fit(c: Column, v: Any) -> Any:
    """Make one value satisfy length / enum / range rules (cheap local repairs)."""
    if v is None:
        return v
    if isinstance(v, str) and c.max_length and len(v) > c.max_length:
        v = v[: c.max_length]
    return _clamp(c, v)


def repair_dataset(schema: Schema, ctx: GenContext, order: list[str], allow_delete: bool = True) -> list[str]:
    ds = ctx.dataset
    notes: list[str] = []
    names = [n for n in order if n in ds] + [n for n in ds if n not in order]
    for name in names:
        t = schema.table(name)
        if not t:
            continue
        removed = _repair_table(schema, ctx, t, allow_delete)
        if removed:
            notes.append(f"{name}: {removed} record(s) removed because no combination satisfying the table's unique / foreign-key rules could be found.")
    return notes


def _unique_cols_ok(t: Table, rows: list[Row], i: int, r: Row, col: str, fk_by: dict) -> bool:
    """A new value picked for `col` must not collide with another row on a single-column UNIQUE of that column."""
    c = next(x for x in t.columns if x.name == col)
    if not (c.unique or c.primary_key):
        return True
    key = str(r[col]).lower()
    return not any(j != i and o.get(col) is not None and str(o[col]).lower() == key for j, o in enumerate(rows))


def _pk_cols(t: Table) -> list[Column]:
    return [c for c in t.columns if c.primary_key]


def _repair_table(schema: Schema, ctx: GenContext, t: Table, allow_delete: bool) -> int:
    rows: list[Row] = ctx.dataset[t.name]
    cols = {c.name: c for c in t.columns}
    fk_by = {f.column: f for f in t.foreign_keys}
    drop: set[int] = set()

    def parent_keys(f: Any) -> list[Any]:
        src = rows if f.ref_table == t.name else ctx.dataset.get(f.ref_table, [])
        return [p.get(f.ref_column) for p in src if p.get(f.ref_column) is not None]

    # 1) cell level: not-null, type, length, enum, numeric range
    for r in rows:
        for c in t.columns:
            if c.generated:
                continue
            v = r.get(c.name)
            if v is None:
                if c.nullable or c.missing:
                    continue
                f = fk_by.get(c.name)
                if f:
                    keys = parent_keys(f)
                    r[c.name] = ctx.pick(keys) if keys else None
                else:
                    r[c.name] = _fit(c, ctx.value(t, c, use_pool=False))
                continue
            if c.enum_values and str(v) not in c.enum_values:
                v = ctx.pick(c.enum_values)
            if not _type_ok(c, v):
                v = ctx.value(t, c, use_pool=False)
            r[c.name] = _fit(c, v)

    # 2) foreign keys must point at an existing parent (parents were repaired first)
    for i, r in enumerate(rows):
        for f in t.foreign_keys:
            v = r.get(f.column)
            if v is None:
                continue
            keys = parent_keys(f)
            if v in set(keys):
                continue
            col = cols[f.column]
            if keys and not (f.ref_table == t.name and i == 0):
                r[f.column] = ctx.pick([k for k in keys if k != r.get(f.ref_column)] or keys)
            elif col.nullable:
                r[f.column] = None
            else:
                drop.add(i)

    # 3) single-column uniqueness (PK and UNIQUE), case-insensitive for text.
    #    First occurrences keep their value; every later duplicate is re-valued against ALL values currently in use.
    for c in t.columns:
        if not (c.unique or c.primary_key) or c.generated:
            continue
        f = fk_by.get(c.name)
        first: set[str] = set()
        dups: list[int] = []
        for i, r in enumerate(rows):
            if i in drop or r.get(c.name) is None:
                continue
            key = str(r[c.name]).lower()
            if key in first:
                dups.append(i)
            else:
                first.add(key)
        taken = set(first)
        free: Optional[list[Any]] = None
        for i in dups:
            r = rows[i]
            new: Any = None
            if f and f.ref_table != t.name:
                if free is None:
                    free = [k for k in parent_keys(f) if str(k).lower() not in taken]
                new = free.pop() if free else None
            elif c.enum_values:
                left = [x for x in c.enum_values if x.lower() not in taken]
                new = ctx.pick(left) if left else None
            else:
                for attempt in range(150):
                    cand = _fit(c, ctx._bump(ctx.value(t, c, use_pool=False), attempt, c))
                    if cand is not None and str(cand).lower() not in taken and _type_ok(c, cand):
                        new = cand
                        break
            if new is None:
                if c.nullable:
                    r[c.name] = None
                elif allow_delete:
                    drop.add(i)
                continue
            r[c.name] = new
            taken.add(str(new).lower())

    # 4) composite uniqueness (UNIQUE (a, b), unique indexes and composite primary keys)
    for group in t.unique_together:
        group = [g for g in group if g in cols]
        if not group:
            continue
        first_t: set[tuple] = set()
        dup_rows: list[int] = []
        for i, r in enumerate(rows):
            if i in drop or any(r.get(g) is None for g in group):
                continue
            key = tuple(str(r[g]).lower() for g in group)
            if key in first_t:
                dup_rows.append(i)
            else:
                first_t.add(key)
        taken_t = set(first_t)
        for i in dup_rows:
            r = rows[i]
            fixed = False
            for _ in range(400):
                g = ctx.pick(group)
                c = cols[g]
                f = fk_by.get(g)
                if c.generated:
                    continue
                if f:
                    keys = parent_keys(f)
                    if not keys:
                        continue
                    nv = ctx.pick(keys)
                elif c.enum_values:
                    nv = ctx.pick(c.enum_values)
                else:
                    nv = _fit(c, ctx._bump(ctx.value(t, c, use_pool=False), int(ctx.rng.integers(0, 8)), c))
                old = r[g]
                r[g] = nv
                key = tuple(str(r[x]).lower() for x in group)
                if key not in taken_t and _unique_cols_ok(t, rows, i, r, g, fk_by):
                    taken_t.add(key)
                    fixed = True
                    break
                r[g] = old
            if not fixed and allow_delete:
                drop.add(i)

    # 5) anything still unfixable is removed; rows that referenced it are dealt with when their table is repaired
    if drop:
        keep = [r for i, r in enumerate(rows) if i not in drop]
        ctx.dataset[t.name][:] = keep
        # a removed self-referenced parent may orphan siblings in the same table: re-point or null them
        for r in ctx.dataset[t.name]:
            for f in t.foreign_keys:
                if f.ref_table != t.name or r.get(f.column) is None:
                    continue
                keys = {p.get(f.ref_column) for p in ctx.dataset[t.name]}
                if r[f.column] not in keys:
                    r[f.column] = None if cols[f.column].nullable else (next(iter(keys), None))
    return len(drop)
