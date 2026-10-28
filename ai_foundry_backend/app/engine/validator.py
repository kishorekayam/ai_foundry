# app/engine/validator.py
"""The nine validation checks, run on the generated dataset before any insert is offered."""
from __future__ import annotations

import ipaddress
import json
import re
from datetime import date, datetime, time as dtime
from collections import Counter
from typing import Optional

from ..models import Column, Scenario, ScenarioCoverage, Schema, TestCase, ValidationCheck
from .generator import Dataset, is_date, is_int, is_num, is_text, parse_range


def scenario_coverage(dataset: Dataset, schema: Schema, scenarios: list[Scenario]) -> list[ScenarioCoverage]:
    out: list[ScenarioCoverage] = []
    for s in scenarios:
        table = schema.table(s.table)
        col = next((c for c in table.columns if c.name == s.column), None) if table else None
        if not table or not col:
            out.append(ScenarioCoverage(scenario=s, generated=0, result="Unsupported", note=f"Schema has no {s.table}.{s.column}. The requested state cannot be represented."))
            continue
        if col.enum_values and s.value not in col.enum_values:
            out.append(ScenarioCoverage(scenario=s, generated=0, result="Unsupported", note=f"{s.value} is not permitted by the {s.column} constraint ({', '.join(col.enum_values)})."))
            continue
        gen = sum(1 for r in dataset.get(s.table, []) if str(r.get(s.column)).upper() == s.value.upper())
        result = "Covered" if gen >= s.count else ("Missing" if gen == 0 else "Partial")
        out.append(ScenarioCoverage(scenario=s, generated=gen, result=result, note=None if result == "Covered" else f"{s.count - gen} more required."))  # type: ignore[arg-type]
    return out


def _type_ok(c: Column, v) -> bool:
    """Mirror what the database will accept for each type, so 'valid here' means 'loads there'."""
    t = c.type.lower()
    if t == "objectid":
        return isinstance(v, str) and re.fullmatch(r"[0-9a-f]{24}", v) is not None
    if t == "uuid":
        return isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", v) is not None
    if t in {"boolean", "bool"}:
        return isinstance(v, bool)
    if is_int(t):
        return isinstance(v, int) and not isinstance(v, bool)
    if is_num(t):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False
        if c.precision is not None and abs(v) >= 10 ** (c.precision - (c.scale or 0)):
            return False
        return True
    if t == "date":
        if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return False
        try:
            date.fromisoformat(v)
            return True
        except ValueError:
            return False
    if is_date(t):
        if not isinstance(v, str) or not re.match(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", v):
            return False
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False
    if t == "time":
        try:
            return isinstance(v, str) and (dtime.fromisoformat(v) is not None)
        except ValueError:
            return False
    if t == "json":
        try:
            json.loads(v) if isinstance(v, str) else json.dumps(v)
            return True
        except (TypeError, ValueError):
            return False
    if t == "inet":
        try:
            ipaddress.ip_interface(v)
            return True
        except ValueError:
            return False
    if t == "interval":
        return isinstance(v, str) and re.fullmatch(r"\d+ (?:second|minute|hour|day)s?", v) is not None
    if t == "bytea":
        return isinstance(v, str) and re.fullmatch(r"\\x(?:[0-9a-fA-F]{2})*", v) is not None
    if t.startswith("array:"):
        return isinstance(v, list)
    if is_text(t):
        return isinstance(v, str)
    return True


def validate(schema: Schema, dataset: Dataset, coverage: Optional[list[ScenarioCoverage]] = None, test_cases: Optional[list[TestCase]] = None) -> list[ValidationCheck]:
    acc = {k: [0, 0] for k in ("type", "req", "len", "pk", "fk", "uq", "en")}
    where: dict[str, Counter] = {k: Counter() for k in acc}
    here = ["", ""]  # current table, column

    def bump(k: str, ok: bool) -> None:
        acc[k][0] += 1
        if not ok:
            acc[k][1] += 1
            where[k][".".join(x for x in here if x)] += 1

    for t in schema.tables:
        if t.name not in dataset:
            continue
        rows = dataset[t.name]
        here[0] = t.name
        pk_sets = {c.name: set() for c in t.columns if c.primary_key}
        uq_sets = {c.name: set() for c in t.columns if c.unique and not c.primary_key}
        composite = [(tuple(u), set()) for u in t.unique_together]
        fk_values = {f.column: {r.get(f.ref_column) for r in (rows if f.ref_table == t.name else dataset.get(f.ref_table, []))} for f in t.foreign_keys}
        for r in rows:
            for c in t.columns:
                v = r.get(c.name)
                here[1] = c.name
                if v is None:
                    bump("req", c.nullable or bool(c.missing))
                    continue
                bump("req", True)
                bump("type", _type_ok(c, v))
                if c.max_length and isinstance(v, str):
                    bump("len", len(v) <= c.max_length)
                if c.enum_values:
                    bump("en", str(v) in c.enum_values)
                if c.check and isinstance(v, (int, float)):
                    lo, hi = parse_range(c.check)
                    bump("en", (lo is None or v >= lo) and (hi is None or v <= hi))
                if c.name in pk_sets:
                    bump("pk", str(v) not in pk_sets[c.name])
                    pk_sets[c.name].add(str(v))
                if c.name in uq_sets:
                    bump("uq", str(v) not in uq_sets[c.name])
                    uq_sets[c.name].add(str(v))
            for cols, seen in composite:
                here[1] = "(" + ",".join(cols) + ")"
                if all(r.get(c) is not None for c in cols):
                    key = tuple(str(r.get(c)) for c in cols)
                    bump("uq", key not in seen)
                    seen.add(key)
            for f in t.foreign_keys:
                v = r.get(f.column)
                here[1] = f.column
                if v is not None:
                    bump("fk", v in fk_values[f.column])

    def mk(id_: str, label: str, pair: list[int]) -> ValidationCheck:
        checked, failed = pair
        key = {"required": "req", "length": "len", "unique": "uq", "enum": "en"}.get(id_, id_)
        top = ", ".join(f"{w} x{n}" for w, n in where[key].most_common(5))
        return ValidationCheck(id=id_, label=label, checked=checked, failed=failed, status="failed" if failed else "passed", detail=f"{failed} of {checked} checked values failed ({top})" if failed else f"{checked} values checked")

    checks = [
        mk("type", "Data type matches field", acc["type"]),
        mk("required", "Required fields not null", acc["req"]),
        mk("length", "String length within limit", acc["len"]),
        mk("pk", "Primary key unique", acc["pk"]),
        mk("fk", "Foreign key references a parent", acc["fk"]),
        mk("unique", "Unique constraint holds", acc["uq"]),
        mk("enum", "Enum and check constraints", acc["en"]),
    ]
    if coverage:
        bad = [c for c in coverage if c.result != "Covered"]
        checks.append(ValidationCheck(id="scenario", label="Scenario counts match request", checked=len(coverage), failed=len(bad), status="warning" if bad else "passed", detail=f"{len(bad)} scenario(s) not fully covered" if bad else f"{len(coverage)} scenario(s) covered"))
    else:
        checks.append(ValidationCheck(id="scenario", label="Scenario counts match request", checked=0, failed=0, status="skipped", detail="No scenarios requested"))
    if test_cases is not None:
        need = [tc for tc in test_cases if tc.prerequisite_records]
        index = {t: {str(v) for r in rows for v in r.values()} for t, rows in dataset.items()}
        bad_tc = [tc for tc in need if any(p.key not in index.get(p.table, set()) for p in tc.prerequisite_records)]
        checks.append(ValidationCheck(id="linkage", label="Test-case linkage exists", checked=len(need), failed=len(bad_tc), status="failed" if bad_tc else "passed", detail=f"{len(need) - len(bad_tc)} of {len(need)} cases have all prerequisite records"))
    else:
        checks.append(ValidationCheck(id="linkage", label="Test-case linkage exists", checked=0, failed=0, status="skipped", detail="Mode 3 only"))
    return checks


def unsupported_constraints(schema: Schema) -> list[str]:
    out: list[str] = []
    for t in schema.tables:
        for c in t.columns:
            if c.check:
                lo, hi = parse_range(c.check)
                if lo is None and hi is None:
                    out.append(f'{t.name}.{c.name}: check "{c.check}" is not automatically validated')
        if t.needs_definition:
            out.append(f"{t.name}: no validator, fields were not discovered")
    if schema.db_type == "mongodb":
        out.append("Cross-collection references are not discoverable from MongoDB metadata")
    out.extend(w for w in schema.warnings if "not automatically" in w or "composite" in w)
    return out
