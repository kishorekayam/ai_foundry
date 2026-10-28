# app/engine/tc_validate.py
"""Validation checks for Mode 3. There is no generated dataset, so the checks target what a test case can get wrong:
a request that does not exist in the collection, a 'valid' request the database would reject, or a negative case that
does not actually break anything."""
from __future__ import annotations

from typing import Any

from ..models import Column, Schema, TestCase, ValidationCheck
from .apisource import ApiSource, key_to_column
from .generator import is_int, parse_range
from .tc_planner import INT_RANGE
from .validator import _type_ok


def body_problems(schema: Schema, table: str, body: dict[str, Any], partial: bool = False) -> list[str]:
    """Why the database (or API contract) would reject this body. Empty list = acceptable."""
    t = schema.table(table)
    if not t or body is None:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for k, v in body.items():
        c: Column | None = key_to_column(t, k)
        if not c:
            continue
        seen.add(c.name)
        if v is None:
            if not c.nullable and not c.primary_key and c.default is None and not c.generated:
                out.append(f"{k} is null")
            continue
        if not _type_ok(c, v):
            out.append(f"{k} has the wrong type")
        elif c.max_length and isinstance(v, str) and len(v) > c.max_length:
            out.append(f"{k} is longer than {c.max_length}")
        elif is_int(c.type) and isinstance(v, int) and not (INT_RANGE.get(c.type.lower(), INT_RANGE["integer"])[0] <= v <= INT_RANGE.get(c.type.lower(), INT_RANGE["integer"])[1]):
            out.append(f"{k} is outside the {c.type} range")
        elif c.enum_values and str(v) not in c.enum_values:
            out.append(f"{k} is not an allowed value")
        elif c.check and isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = parse_range(c.check)
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                out.append(f"{k} is outside its allowed range")
        if isinstance(v, str) and not v.strip() and c.type.lower() in {"varchar", "text", "string"} and not c.nullable and not c.enum_values:
            out.append(f"{k} is blank")
        for f in t.foreign_keys:
            if f.column == c.name and isinstance(v, (int, str)) and str(v) in {"987654321", "00000000-0000-0000-0000-000000000000", "NO_SUCH_PARENT"}:
                out.append(f"{k} points to no {f.ref_table}")
    if not partial:
        for c in t.columns:
            if not c.nullable and not c.primary_key and c.default is None and not c.generated and c.name not in seen and not any(key_to_column(t, k) is c for k in body):
                out.append(f"{c.name} is missing")
    return out


def run_checks(schema: Schema, source: ApiSource, cases: list[TestCase], categories: list[str], tables_with_samples: dict[str, int]) -> list[ValidationCheck]:
    keys = {e.key for e in source.endpoints}
    by_ep = {e.key: e for e in source.endpoints}
    checks: list[ValidationCheck] = []

    def add(id_: str, label: str, checked: int, bad: list[str], warn: bool = False, ok_detail: str = "") -> None:
        status = "passed" if not bad else ("warning" if warn else "failed")
        detail = (f"{len(bad)} of {checked}: " + "; ".join(bad[:4]) + ("…" if len(bad) > 4 else "")) if bad else (ok_detail or f"{checked} checked")
        checks.append(ValidationCheck(id=id_, label=label, checked=checked, failed=len(bad), status=status, detail=detail))

    add("endpoints", "Every case targets a request in your collection", len(cases), [c.id for c in cases if c.endpoint not in keys])

    # positive request bodies must be acceptable to the database: a "valid" case the database rejects is a bad test (or a finding)
    pos = [c for c in cases if c.category == "positive" and c.fixture and c.fixture.body is not None and c.table and c.fixture.method == "POST"]
    bad = []
    for c in pos:
        pb = body_problems(schema, c.table, c.fixture.body or {}, partial=c.fixture.method == "PATCH")  # type: ignore[union-attr]
        pb = [p for p in pb if not p.endswith("is missing") or "only the required" not in c.title]
        if pb:
            bad.append(f"{c.id} ({pb[0]})")
    add("positive", "Valid requests satisfy the database rules", len(pos), bad, warn=True, ok_detail=f"{len(pos)} request bodies checked against column types, lengths, enums and ranges")

    # negative / boundary-negative cases must break at least one rule, otherwise they would not prove anything
    neg = [c for c in cases if c.fixture and c.fixture.expected_status == "4xx" and c.fixture.body is not None and c.table and c.fixture.method in {"POST", "PUT", "PATCH"} and not c.requests and not c.needs_rules]
    weak = []
    for c in neg:
        pb = body_problems(schema, c.table, c.fixture.body or {}, partial=c.fixture.method == "PATCH")  # type: ignore[union-attr]
        if not pb and "no credentials" not in c.title and "duplicate" not in c.title and "does not exist" not in c.title and "malformed" not in c.title:
            weak.append(c.id)
    add("negative", "Negative cases really break a rule", len(neg), weak, ok_detail=f"{len(neg)} negative bodies each violate a column rule")

    missing = [k for k in categories if not any(c.category == k for c in cases)]
    add("coverage", "Every requested category has cases", len(categories), missing, warn=True, ok_detail=f"{len(categories)} categories covered")

    unmatched = sorted({e.key for e in by_ep.values() if not e.table and e.body is not None and any(c.endpoint == e.key for c in cases)})
    add("matching", "Endpoints matched to a table (field rules known)", len({c.endpoint for c in cases}), unmatched, warn=True, ok_detail="Every endpoint with a body was matched to a table")
    if tables_with_samples:
        checks.append(ValidationCheck(id="samples", label="Existing rows used as values", checked=len(tables_with_samples), failed=0, status="passed", detail=", ".join(f"{t}: {n} row(s)" for t, n in tables_with_samples.items())))
    return checks
