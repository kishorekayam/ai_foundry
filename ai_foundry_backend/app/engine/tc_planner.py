# app/engine/tc_planner.py
"""Test-case planner for Mode 3. Cases are written against the endpoints of the user's Postman collection / OpenAPI file.
The database schema (and optionally a few existing rows) tells us which fields are required, unique, bounded or enums.
No records are generated, so there is nothing to load and no key or type conflicts can occur."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..models import Column, Fixture, Schema, Table, TestCase
from .apisource import ApiSource, Endpoint, deep, key_to_column
from .generator import is_date, is_int, is_num, is_text, parse_range

INT_RANGE = {"smallint": (-32768, 32767), "integer": (-2147483648, 2147483647), "int": (-2147483648, 2147483647), "serial": (1, 2147483647), "bigint": (-(2**63), 2**63 - 1), "bigserial": (1, 2**63 - 1)}
ORDER = ["positive", "negative", "boundary", "workflow"]
PER_ENDPOINT = {"positive": 5, "negative": 14, "boundary": 8}  # cases kept per endpoint and category
MAX_CASES = 300
BAD_ID = 987654321
STATUS_RE = re.compile(r"^[2-5]\d\d$|^[2-5]xx$")


def _ok_text(ep: Endpoint) -> str:
    return f"Accepted ({ep.ok_status})" if ep.ok_status[1:] != "xx" else "Accepted (HTTP 2xx)"


class Planner:
    def __init__(self, source: ApiSource, schema: Schema, categories: list[str], samples: Optional[dict[str, list[dict[str, Any]]]] = None, rules_supplied: bool = False):
        self.src, self.schema, self.cats = source, schema, set(categories)
        self.samples = samples or {}
        self.rules = rules_supplied
        self.notes: list[str] = []

    # ---- field knowledge -----------------------------------------------------------------
    def table(self, ep: Endpoint) -> Optional[Table]:
        return self.schema.table(ep.table) if ep.table else None

    def col(self, ep: Endpoint, key: str) -> Optional[Column]:
        t = self.table(ep)
        return key_to_column(t, key) if t else None

    def required(self, ep: Endpoint) -> tuple[list[str], bool]:
        """(required request fields, whether this is known from the DB schema / contract rather than guessed)"""
        body = ep.body or {}
        req = [k for k in ep.required if k in body]
        t = self.table(ep)
        if t:
            for k in body:
                c = key_to_column(t, k)
                if c and not c.nullable and not c.primary_key and not c.generated and c.default is None and k not in req:
                    req.append(k)
        return req, bool(t or ep.required)

    def sample_row(self, ep: Endpoint) -> Optional[dict[str, Any]]:
        rows = self.samples.get(ep.table or "")
        return rows[0] if rows else None

    # ---- case factory --------------------------------------------------------------------
    def make(self, ep: Endpoint, cat: str, title: str, expected: str, status: str, body: Optional[dict[str, Any]], *, pre: Optional[list[str]] = None, steps: Optional[list[str]] = None,
             needs_rules: bool = False, path: Optional[str] = None, headers: Optional[dict[str, str]] = None, chain: Optional[list[Fixture]] = None) -> TestCase:
        p = path or ep.path
        fx = Fixture(method=ep.method, path=p, body=body, headers=headers if headers is not None else dict(ep.headers), expected_status=status)
        label = f"{ep.method} {p}"
        return TestCase(
            id="", category=cat, title=f"{title}", table=ep.table or "", preconditions=pre or ["None"], steps=steps or [f"Send {label}" + (" with the request body below" if body is not None else "")],
            expected=expected, needs_rules=needs_rules, prerequisite_records=[], fixture=chain[0] if chain else fx, requests=chain, endpoint=ep.key, ready=(not needs_rules) or self.rules,
            readiness_note="Ready to run" if not needs_rules else ("Ready: expected behaviour taken from the supplied rules" if self.rules else "Needs application rules: the schema and collection cannot define this behaviour"),
        )

    def base_body(self, ep: Endpoint) -> Optional[dict[str, Any]]:
        if ep.body is None:
            return None
        body = deep(ep.body)
        row, t = self.sample_row(ep), self.table(ep)
        if row and t:  # values that must reference existing parents come from rows that are really in the database
            for f in t.foreign_keys:
                for k in list(body):
                    c = key_to_column(t, k)
                    if c and c.name == f.column and row.get(f.column) is not None:
                        body[k] = row[f.column]
        return body

    def pre_for_sample(self, ep: Endpoint) -> list[str]:
        t = self.table(ep)
        if self.sample_row(ep) and t and t.foreign_keys:
            return [f"Parent ids ({', '.join(f.column for f in t.foreign_keys)}) taken from rows that exist in your database"]
        return []

    # ---- per-endpoint rule cases ---------------------------------------------------------
    def for_endpoint(self, ep: Endpoint) -> list[TestCase]:
        out: list[TestCase] = []
        body = self.base_body(ep)
        label = ep.name or ep.key
        mutating = ep.method in {"POST", "PUT", "PATCH"} and body is not None
        pre = self.pre_for_sample(ep)
        if ep.has_path_param():
            pre = pre + ["A record exists for the id used in the path (set the id variable, or run the workflow cases that create one)"]
        row = self.sample_row(ep)
        path = ep.path
        if ep.method == "GET" and ep.has_path_param() and row and self.table(ep):
            pk = next((c.name for c in self.table(ep).columns if c.primary_key), None)  # type: ignore[union-attr]
            if pk and row.get(pk) is not None:
                path = re.sub(r"\{[^}]+\}", str(row[pk]), ep.path)
                pre = ["Uses a record that exists in your database"]

        if "positive" in self.cats and ep.method != "DELETE":  # a lone DELETE needs an existing record: the workflow cases create and delete one
            out.append(self.make(ep, "positive", f"{label}: valid request", f"{_ok_text(ep)} and the response matches the contract", ep.ok_status, body, pre=pre or None, path=path))
            if mutating:
                req, known = self.required(ep)
                optional = [k for k in body if k not in req]  # type: ignore[union-attr]
                if known and req and optional:
                    out.append(self.make(ep, "positive", f"{label}: only the required fields ({', '.join(req[:4])}{'…' if len(req) > 4 else ''})", _ok_text(ep), ep.ok_status, {k: body[k] for k in req}, pre=pre or None, steps=[f"Send {ep.method} {ep.path} with required fields only"]))  # type: ignore[index]
                seen = 0
                for k in body:  # type: ignore[union-attr]
                    c = self.col(ep, k)
                    if c and c.enum_values and seen < 2:
                        for v in [x for x in c.enum_values if x != str(body[k])][:2]:
                            out.append(self.make(ep, "positive", f"{label}: {k} = {v}", _ok_text(ep), ep.ok_status, {**body, k: v}, pre=pre or None))
                        seen += 1

        if "negative" in self.cats:
            out += self._negatives(ep, body, label, mutating, pre)
        if "boundary" in self.cats and mutating:
            out += self._boundaries(ep, body, label)  # type: ignore[arg-type]
        kept: list[TestCase] = []
        for cat, n in PER_ENDPOINT.items():
            kept += [c for c in out if c.category == cat][:n]
        return kept

    def _negatives(self, ep: Endpoint, body: Optional[dict[str, Any]], label: str, mutating: bool, pre: list[str]) -> list[TestCase]:
        out: list[TestCase] = []
        if mutating and body is not None:
            req, known = self.required(ep)
            if ep.method in {"POST", "PUT"}:
                for k in (req if known else list(body))[: 6 if known else 3]:
                    nb = {x: v for x, v in body.items() if x != k}
                    out.append(self.make(ep, "negative", f"{label}: missing {k}", f"Rejected with a 4xx validation error ({k} is {'required' if known else 'expected to be required'})", "4xx", nb, pre=pre or None, steps=[f"Send {ep.method} {ep.path} without {k}"], needs_rules=not known))
            for k in req[:3]:
                out.append(self.make(ep, "negative", f"{label}: {k} is null", f"Rejected with a 4xx validation error ({k} may not be null)", "4xx", {**body, k: None}, pre=pre or None, steps=[f"Send {ep.method} {ep.path} with {k}=null"]))
            bad_done = 0
            for k, v in body.items():
                c = self.col(ep, k)
                bad = self._wrong_type(c, v)
                if bad is not None and bad_done < 4:
                    bad_done += 1
                    out.append(self.make(ep, "negative", f"{label}: {k} has the wrong type", f"Rejected with a 4xx validation error ({k} must be {c.type if c else type(v).__name__})", "4xx", {**body, k: bad}, pre=pre or None, steps=[f"Send {ep.method} {ep.path} with {k}={json.dumps(bad)}"]))
            for k in body:
                c = self.col(ep, k)
                if c and c.enum_values:
                    out.append(self.make(ep, "negative", f"{label}: {k} is not an allowed value", f"Rejected with a 4xx validation error (allowed: {', '.join(c.enum_values[:6])})", "4xx", {**body, k: "INVALID_VALUE"}, pre=pre or None))
                    break
            t = self.table(ep)
            if t:
                for f in t.foreign_keys[:2]:
                    k = next((x for x in body if (cc := key_to_column(t, x)) and cc.name == f.column), None)
                    c = key_to_column(t, k) if k else None
                    if k and c:
                        ghost: Any = BAD_ID if is_int(c.type) else "00000000-0000-0000-0000-000000000000" if c.type.lower() == "uuid" else "NO_SUCH_PARENT"
                        out.append(self.make(ep, "negative", f"{label}: {k} references a record that does not exist", f"Rejected with a 4xx error ({f.ref_table} {ghost} does not exist)", "4xx", {**body, k: ghost}, pre=pre or None))
                if ep.method == "POST":
                    for k in list(body)[:30]:
                        c = key_to_column(t, k)
                        if c and c.unique and not c.primary_key:
                            row = self.sample_row(ep)
                            if row and row.get(c.name) is not None:
                                out.append(self.make(ep, "negative", f"{label}: duplicate {k}", f"Rejected with a 4xx conflict/validation error ({k} must be unique)", "4xx", {**body, k: row[c.name]},
                                                     pre=[f"A record with {k} = {row[c.name]!r} already exists (read from your database)"]))
                            else:
                                steps = [f"Send {ep.method} {ep.path} with the body below", "Send the identical request again"]
                                chain = [Fixture(method=ep.method, path=ep.path, body=body, headers=dict(ep.headers), expected_status=ep.ok_status), Fixture(method=ep.method, path=ep.path, body=body, headers=dict(ep.headers), expected_status="4xx")]
                                out.append(self.make(ep, "negative", f"{label}: duplicate {k}", f"The first request is accepted; the repeat is rejected with a 4xx conflict ({k} must be unique)", "4xx", body, steps=steps, chain=chain,
                                                     pre=["Run on a test environment: the first request creates a record"]))
                            break
            if ep.method in {"POST", "PUT"}:
                out.append(self.make(ep, "negative", f"{label}: empty body", "Rejected with a 4xx validation error", "4xx", {}, steps=[f"Send {ep.method} {ep.path} with an empty JSON object"], needs_rules=not known))
        if ep.has_path_param():
            nb = {k: v for k, v in (body or {}).items()} if body is not None else None
            out.append(self.make(ep, "negative", f"{label}: record does not exist", "Rejected with 404 (or another 4xx)", "4xx", nb, path=re.sub(r"\{[^}]+\}", str(BAD_ID), ep.path), steps=[f"Send {ep.method} with an id that does not exist ({BAD_ID})"]))
            out.append(self.make(ep, "negative", f"{label}: malformed id", "Rejected with a 4xx error", "4xx", nb, path=re.sub(r"\{[^}]+\}", "not-an-id", ep.path), steps=[f"Send {ep.method} with id 'not-an-id'"]))
        if any(k.lower() == "authorization" for k in ep.headers):
            out.append(self.make(ep, "negative", f"{label}: no credentials", "Rejected with 401 or 403", "4xx", body, headers={k: v for k, v in ep.headers.items() if k.lower() != "authorization"}, steps=[f"Send {ep.method} {ep.path} without the Authorization header"], needs_rules=False))
        return out

    @staticmethod
    def _wrong_type(c: Optional[Column], v: Any) -> Any:
        t = c.type.lower() if c else ""
        if t in {"boolean", "bool"} or isinstance(v, bool):
            return "not-a-boolean"
        if (c and (is_int(t) or is_num(t))) or isinstance(v, (int, float)):
            return "abc"
        if (c and is_date(t)) or (isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v)):
            return "not-a-date"
        if t == "uuid":
            return "not-a-uuid"
        return None

    def _boundaries(self, ep: Endpoint, body: dict[str, Any], label: str) -> list[TestCase]:
        out: list[TestCase] = []
        t = self.table(ep)
        if not t:
            return out
        n = 0
        for k in body:
            c = key_to_column(t, k)
            if not c or c.primary_key or c.generated or n >= 4:
                continue
            ty = c.type.lower()
            if c.max_length and is_text(ty):
                n += 1
                out.append(self.make(ep, "boundary", f"{label}: {k} at maximum length ({c.max_length})", _ok_text(ep), ep.ok_status, {**body, k: "a" * c.max_length}, steps=[f"Send {k} with exactly {c.max_length} characters"]))
                out.append(self.make(ep, "boundary", f"{label}: {k} over maximum length ({c.max_length + 1})", f"Rejected with a 4xx validation error ({k} is limited to {c.max_length} characters)", "4xx", {**body, k: "a" * (c.max_length + 1)}, steps=[f"Send {k} with {c.max_length + 1} characters"]))
            elif is_int(ty) and not any(f.column == c.name for f in t.foreign_keys):
                n += 1
                lo, hi = parse_range(c.check)
                rng = INT_RANGE.get(ty, INT_RANGE["integer"])
                top, bottom = (int(hi) if hi is not None else rng[1]), (int(lo) if lo is not None else rng[0])
                out.append(self.make(ep, "boundary", f"{label}: {k} at maximum ({top})", _ok_text(ep), ep.ok_status, {**body, k: top}))
                out.append(self.make(ep, "boundary", f"{label}: {k} above maximum ({top + 1})", f"Rejected with a 4xx validation error ({k} must be at most {top})", "4xx", {**body, k: top + 1}))
                if lo is not None:
                    out.append(self.make(ep, "boundary", f"{label}: {k} below minimum ({bottom - 1})", f"Rejected with a 4xx validation error ({k} must be at least {bottom})", "4xx", {**body, k: bottom - 1}))
            elif is_num(ty) and c.precision:
                n += 1
                whole = c.precision - (c.scale or 0)
                mx = round(10**whole - 10 ** -(c.scale or 0), c.scale or 0)
                out.append(self.make(ep, "boundary", f"{label}: {k} at largest allowed value ({mx})", _ok_text(ep), ep.ok_status, {**body, k: mx}))
                out.append(self.make(ep, "boundary", f"{label}: {k} too large ({10**whole})", f"Rejected with a 4xx validation error ({k} allows {whole} digits before the decimal point)", "4xx", {**body, k: 10**whole}))
        for k in body:
            c = key_to_column(t, k)
            if c and is_text(c.type) and not c.nullable and not c.primary_key and not c.enum_values:
                out.append(self.make(ep, "boundary", f"{label}: {k} is an empty string", "Rejected or accepted according to the application's blank-value rule", "4xx", {**body, k: ""}, needs_rules=True, steps=[f"Send {k} as an empty string"]))
                break
        return out

    # ---- workflows -----------------------------------------------------------------------
    def workflows(self) -> list[TestCase]:
        out: list[TestCase] = []
        groups: dict[str, list[Endpoint]] = {}
        for ep in self.src.endpoints:
            groups.setdefault(ep.resource(), []).append(ep)
        for root, eps in groups.items():
            post = next((e for e in eps if e.method == "POST" and not e.has_path_param() and e.body is not None), None)
            if not post:
                continue
            items = {e.method: e for e in self.src.endpoints if e.has_path_param() and e.resource() == root}
            body = self.base_body(post) or {}
            t = self.table(post)
            pk = next((c.name for c in t.columns if c.primary_key), "id") if t else "id"
            idp = "{{createdId}}"
            h = dict(post.headers)

            def step(ep: Endpoint, b: Optional[dict[str, Any]], status: str, note: Optional[str] = None) -> Fixture:
                return Fixture(method=ep.method, path=re.sub(r"\{[^}]+\}", idp, ep.path), body=b, headers=dict(ep.headers or h), expected_status=status, note=note)

            create = Fixture(method="POST", path=post.path, body=body, headers=h, expected_status=post.ok_status, note=f"capture-id:{pk}")
            label = post.name or root
            if (g := items.get("GET")):
                out.append(self.make(post, "workflow", f"{label}: create, then retrieve it", "The record is created and then returned by id with the submitted values", "2xx", body, chain=[create, step(g, None, g.ok_status)],
                                     steps=[f"POST {post.path}", "Read the new id from the response", f"GET {g.path} with that id"], pre=self.pre_for_sample(post) or None))
            upd = items.get("PATCH") or items.get("PUT")
            if upd:
                key = next((k for k, v in body.items() if isinstance(v, str) and (c := key_to_column(t, k) if t else None) and not c.unique and not c.enum_values and is_text(c.type) and not c.primary_key), None) if t else next((k for k, v in body.items() if isinstance(v, str)), None)
                if key:
                    new = f"{str(body[key])[: max(1, ((key_to_column(t, key).max_length or 60) if t else 60) - 8)]} updated"  # type: ignore[union-attr]
                    ub = {key: new} if upd.method == "PATCH" else {**body, key: new}
                    chain = [create, step(upd, ub, upd.ok_status)] + ([step(items["GET"], None, "2xx")] if "GET" in items else [])
                    out.append(self.make(post, "workflow", f"{label}: create, then update {key}", f"The record is created and {key} is changed to the new value", "2xx", body, chain=chain,
                                         steps=[f"POST {post.path}", f"{upd.method} {upd.path} changing {key}"] + (["GET it again and compare"] if "GET" in items else [])))
            if (d := items.get("DELETE")):
                chain = [create, step(d, None, d.ok_status)] + ([step(items["GET"], None, "4xx")] if "GET" in items else [])
                out.append(self.make(post, "workflow", f"{label}: create, delete, then confirm it is gone", "The record is created, deleted, and no longer retrievable" if "GET" in items else "The record is created and deleted", "2xx", body, chain=chain,
                                     steps=[f"POST {post.path}", f"DELETE {d.path}"] + ([f"GET {items['GET'].path} returns 4xx"] if "GET" in items else [])))
            lst = next((e for e in eps if e.method == "GET" and not e.has_path_param() and e.path == root), None)
            if lst:
                out.append(self.make(post, "workflow", f"{label}: create, then it appears in the list", "The new record is present in the list response", "2xx", body, chain=[create, step(lst, None, lst.ok_status)], steps=[f"POST {post.path}", f"GET {lst.path}"]))
        return out

    def plan(self, selected: Optional[list[str]] = None) -> list[TestCase]:
        eps = [e for e in self.src.endpoints if not selected or e.key in selected]
        cases: list[TestCase] = []
        for ep in eps:
            cases += self.for_endpoint(ep)
        if "workflow" in self.cats:
            sel = {e.key for e in eps}
            cases += [c for c in self.workflows() if c.endpoint in sel]
        return cases


def finalize(cases: list[TestCase]) -> list[TestCase]:
    seen: set[str] = set()
    out: list[TestCase] = []
    for c in cases:
        fx = c.fixture
        sig = json.dumps([c.category, c.endpoint, fx.path if fx else "", fx.body if fx else None, [r.model_dump() for r in c.requests] if c.requests else None, sorted((fx.headers or {}).keys()) if fx else None], sort_keys=True, default=str)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    out.sort(key=lambda c: ORDER.index(c.category))  # stable: keeps endpoint order inside each category
    out = out[:MAX_CASES]
    for i, c in enumerate(out, start=1):
        c.id = f"TC{i:03d}"
    return out


def from_ai(raw: dict[str, Any], planner: Planner, eps: list[Endpoint]) -> list[TestCase]:
    """Extra cases proposed by the LLM. Only edits to fields that really exist in the endpoint's body are accepted."""
    out: list[TestCase] = []
    for c in (raw.get("cases") or [])[:40]:
        try:
            ep = eps[int(c["endpoint"])]
            cat = c["category"]
            if cat not in planner.cats or ep.body is None:
                continue
            body = planner.base_body(ep) or {}
            sets = {k: v for k, v in (c.get("set") or {}).items() if k in body and (v is None or isinstance(v, (str, int, float, bool)))}
            omit = [k for k in (c.get("omit") or []) if k in body]
            if not sets and not omit:
                continue
            nb = {k: v for k, v in {**body, **sets}.items() if k not in omit}
            status = str(c.get("expectedStatus", ""))
            if not STATUS_RE.match(status):
                status = "4xx" if cat == "negative" else ep.ok_status
            out.append(planner.make(ep, cat, str(c["title"])[:160], str(c["expected"])[:240], status, nb, needs_rules=bool(c.get("needsRules")), pre=[str(x) for x in c.get("preconditions", [])][:4] or None,
                                    steps=[f"Send {ep.method} {ep.path}" + (f" with {', '.join(f'{k}={json.dumps(v)}' for k, v in sets.items())}" if sets else "") + (f" without {', '.join(omit)}" if omit else "")]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out
