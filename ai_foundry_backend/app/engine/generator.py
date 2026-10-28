# app/engine/generator.py
"""Synthetic data generation core shared by all three modes.

Faker supplies names/e-mails/dates, NumPy the numeric distributions, NetworkX the parent-child ordering.
Parents are always generated before children; cycles and self references are reported, never bypassed.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import networkx as nx
import numpy as np
from faker import Faker

from ..models import Column, Schema, Table

Row = dict[str, Any]
Dataset = dict[str, list[Row]]

LOCALES = {"en_IN": "en_IN", "en_US": "en_US", "en_GB": "en_GB", "de": "de_DE", "fr": "fr_FR"}
COUNTRY = {"en_IN": "India", "en_US": "United States", "en_GB": "United Kingdom", "de": "Germany", "fr": "France"}

INT_TYPES = {"serial", "bigserial", "integer", "int", "bigint", "smallint", "long"}
NUM_TYPES = {"numeric", "decimal", "float", "double", "real", "number"}
DATE_TYPES = {"date", "timestamp", "timestamptz", "datetime"}
TEXT_TYPES = {"varchar", "text", "string", "char"}

is_int = lambda t: t.lower() in INT_TYPES  # noqa: E731
is_num = lambda t: t.lower() in NUM_TYPES  # noqa: E731
is_date = lambda t: t.lower() in DATE_TYPES  # noqa: E731
is_text = lambda t: t.lower() in TEXT_TYPES  # noqa: E731


def parse_range(check: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    if not check:
        return None, None
    m = re.search(r"BETWEEN\s+(-?\d+(?:\.\d+)?)\s+AND\s+(-?\d+(?:\.\d+)?)", check, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))
    lo = hi = None
    if (g := re.search(r">=\s*(-?\d+(?:\.\d+)?)", check)):
        lo = float(g.group(1))
    elif (g := re.search(r">\s*(-?\d+(?:\.\d+)?)", check)):
        lo = float(g.group(1)) + 1
    if (g := re.search(r"<=\s*(-?\d+(?:\.\d+)?)", check)):
        hi = float(g.group(1))
    elif (g := re.search(r"<\s*(-?\d+(?:\.\d+)?)", check)):
        hi = float(g.group(1)) - 1
    return lo, hi


def coerce_value(col: Column, value: Any) -> Any:
    """Turn a scenario value written as text ("TRUE", "5") into the column's real type."""
    t = col.type.lower()
    v = str(value)
    if t in {"boolean", "bool"}:
        return v.strip().lower() in {"true", "t", "1", "yes", "y"}
    try:
        if is_int(t):
            return int(float(v))
        if is_num(t):
            return float(v)
    except ValueError:
        return value
    return value


def dependency_order(schema: Schema, selected: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Returns (order, cyclic, self_referencing) using a NetworkX dependency graph."""
    g = nx.DiGraph()
    g.add_nodes_from(n for n in (t.name for t in schema.tables) if n in selected)
    self_refs: list[str] = []
    for t in schema.tables:
        if t.name not in selected:
            continue
        for f in t.foreign_keys:
            if f.ref_table == t.name:
                self_refs.append(t.name)
            elif f.ref_table in selected:
                g.add_edge(f.ref_table, t.name)
    order: list[str] = []
    cyclic: list[str] = []
    condensed = nx.condensation(g)
    for comp in nx.topological_sort(condensed):
        members = sorted(condensed.nodes[comp]["members"])
        if len(members) > 1:
            cyclic.extend(members)
        else:
            order.append(members[0])
    # keep the schema's table order within a topological generation for stable output
    return order, cyclic, sorted(set(self_refs))


def required_parents(schema: Schema, selected: set[str]) -> list[str]:
    added: list[str] = []

    def visit(name: str) -> None:
        t = schema.table(name)
        if not t:
            return
        for f in t.foreign_keys:
            col = next((c for c in t.columns if c.name == f.column), None)
            if f.ref_table == name or f.ref_table in selected or (col and col.nullable):
                continue
            selected.add(f.ref_table)
            added.append(f.ref_table)
            visit(f.ref_table)

    for n in list(selected):
        visit(n)
    return added


class GenContext:
    def __init__(self, schema: Schema, locale: str, seed: Optional[int] = None, domain: Optional[str] = None, pools: Optional[dict[tuple[str, str], list[str]]] = None):
        self.schema = schema
        self.locale = locale
        self.faker = Faker(LOCALES.get(locale, "en_US"))
        s = seed if seed is not None else int(np.random.default_rng().integers(0, 2**31 - 1))
        self.faker.seed_instance(s)
        self.rng = np.random.default_rng(s)
        self.dataset: Dataset = {}
        self.counters: dict[str, int] = {}
        self.uniques: dict[str, set[str]] = {}
        self.pools = pools or {}
        self.composites: dict[tuple, set] = {}
        self._no_pool = False
        self._fk_perm: dict[tuple, list] = {}
        self.table_map = {t.name: t for t in schema.tables}

    # ---- helpers -------------------------------------------------------------------------
    def pick(self, seq: list[Any]) -> Any:
        return seq[int(self.rng.integers(0, len(seq)))]

    def _uniq(self, table: str, col: Column, make) -> Any:
        key = f"{table}.{col.name}"
        seen = self.uniques.setdefault(key, set())
        for attempt in range(40):
            v = make(attempt)
            if isinstance(v, str) and col.max_length:
                v = v[: col.max_length]
            if str(v).lower() not in seen:
                seen.add(str(v).lower())
                return v
        base = make(0)
        fb: Any = len(seen) + 100000 if isinstance(base, (int, float)) else f"{str(base)[: max(1, (col.max_length or 40) - 7)]}-{len(seen) + 1}"
        if isinstance(fb, str) and col.max_length:
            fb = fb[-col.max_length :]
        seen.add(str(fb).lower())
        return fb

    def _recent(self, days_back: int, days_ahead: int = 0) -> datetime:
        now = datetime.now(timezone.utc)
        offset = float(self.rng.uniform(-days_back, days_ahead))
        return now + timedelta(days=offset)

    def _numeric(self, c: Column, integer: bool) -> Any:
        lo, hi = parse_range(c.check)
        tk = self._tokens(c.name)
        mn, mx = (lo if lo is not None else 0), (hi if hi is not None else 1000)
        if lo is None and hi is None:
            if "year" in tk:
                mn, mx = 2000, 2025
            elif tk & {"age"}:
                mn, mx = 18, 80
            elif tk & {"price", "amount", "cost", "total", "salary", "fee", "balance", "revenue"}:
                mn, mx = 10, 5000
            elif tk & {"qty", "quantity", "stock", "count", "units"}:
                mn, mx = 1, 100
            elif tk & {"percent", "percentage", "pct", "ratio", "rate", "progress"}:
                mn, mx = 0, 100
            elif tk & {"rating", "stars"}:
                mn, mx = 1, 5
            elif tk & {"latitude", "lat"}:
                mn, mx = -60, 70
            elif tk & {"longitude", "lng", "lon"}:
                mn, mx = -120, 140
            elif "port" in tk:
                mn, mx = 1024, 65535
        if lo is not None and hi is None:
            mx = lo + 1000
        if hi is not None and lo is None:
            mn = min(0, hi)
        scale = c.scale if c.scale is not None else 2
        if c.precision is not None:  # numeric(p, s): never exceed what the column can hold
            limit = 10 ** (c.precision - (c.scale or 0)) - 10 ** -(c.scale or 0)
            mx, mn = min(mx, limit), max(mn, -limit)
            if mn > mx:
                mn = mx
        if integer:
            return int(self.rng.integers(int(np.ceil(mn)), int(np.floor(mx)) + 1))
        return round(float(self.rng.triangular(mn, (mn + mx) / 2 + (mx - mn) * 0.1, mx)), scale)

    @staticmethod
    def _texty(t: str) -> bool:
        return is_text(t) or t not in {"boolean", "bool", "uuid", "json", "inet", "time", "interval", "bytea", "objectid", "date"} and not (is_int(t) or is_num(t) or is_date(t) or t.startswith("array:"))

    @staticmethod
    def _tokens(name: str) -> set[str]:
        parts = re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower())
        return {p for p in parts if p}

    def _by_name(self, table: str, c: Column) -> Any:
        """Semantic value for TEXT columns from the words in the column / table name. Works for any schema."""
        f = self.faker
        pool = None if self._no_pool else self.pools.get((table, c.name))
        if pool:
            return self.pick(pool)
        n = c.name.lower()
        tk = self._tokens(c.name)
        tt = self._tokens(table)
        compact = n.replace("_", "")
        has = lambda *w: any(x in tk for x in w)  # noqa: E731
        near = lambda *w: any(x in compact for x in w)  # noqa: E731
        mx = c.max_length or 60
        if near("email"):
            return f.email().lower()
        if has("phone", "mobile", "tel", "telephone", "fax", "msisdn"):
            return f.phone_number()
        if near("firstname", "givenname") or has("first", "given", "forename"):
            return f.first_name()
        if near("lastname", "familyname") or has("last", "surname", "family"):
            return f.last_name()
        if has("username", "login", "handle", "nickname") or near("username"):
            return f.user_name()
        if has("password", "passwd", "hash", "digest", "checksum"):
            return f.sha256()[:mx]
        if has("token", "secret", "apikey") or near("apikey", "accesskey"):
            return f.sha1()[:mx]
        if has("slug"):
            return "-".join(f.words(nb=3))
        if has("url", "uri", "link", "href", "website", "homepage"):
            return f.url()
        if has("domain", "hostname", "host", "subdomain", "fqdn"):
            return f.domain_name()
        if has("ip", "ipv4") or near("ipaddress"):
            return f.ipv4()
        if has("color", "colour") or near("hexcolor", "colorhex"):
            return f.hex_color() if mx <= 7 else f.color_name()
        if has("currency"):
            return f.currency_code()
        if has("language", "lang", "locale"):
            return f.language_code()
        if has("timezone", "tz"):
            return f.timezone()
        if has("country"):
            return f.country_code() if mx <= 3 else (COUNTRY.get(self.locale) or f.current_country())
        if has("city", "town"):
            return f.city()
        if has("state", "province", "region") and not has("status"):
            return f.state()
        if has("zip", "postal", "postcode", "pincode") or near("zipcode", "postalcode"):
            return f.postcode()
        if has("address", "street", "addr") or near("addressline"):
            return f.street_address()
        if has("gender", "sex"):
            return self.pick(["Male", "Female", "Other"])
        if has("company", "organization", "organisation", "org", "employer", "vendor", "supplier", "business"):
            return f.company()
        if has("job", "designation", "occupation", "position") or near("jobtitle", "roletitle"):
            return f.job()
        if has("sku", "barcode", "isbn", "ean", "upc"):
            return f.bothify("????-########").upper()
        if has("code", "ref", "reference", "number", "no") and mx <= 30:
            return f.bothify("??-#####").upper()
        if has("title", "subject", "headline", "caption", "label"):
            return f.sentence(nb_words=5).rstrip(".")
        if has("description", "notes", "note", "comment", "comments", "remarks", "message", "body", "summary", "bio", "details", "content", "text", "reason"):
            return f.sentence() if mx < 200 else f.paragraph()
        if has("name") or n == "name":
            if has("full", "display", "person", "contact", "owner", "author", "customer", "client", "user", "employee", "member", "staff", "patient", "student", "teacher", "manager", "supervisor", "head"):
                return f.name()
            if tt & {"user", "users", "person", "people", "customer", "customers", "employee", "employees", "member", "members", "contact", "contacts", "staff", "patient", "patients", "student", "students", "teacher", "teachers", "author", "authors", "profile", "profiles", "account", "accounts"}:
                return f.name()
            if tt & {"company", "companies", "organization", "organizations", "vendor", "vendors", "supplier", "suppliers", "provider", "providers", "tenant", "tenants", "client", "clients", "business", "businesses", "employer", "employers", "partner", "partners", "brand", "brands"}:
                return f.company()
            if has("file", "document", "image", "photo"):
                return f.file_name()
            return f.catch_phrase()
        return None

    def next_key(self, table: str, c: Column) -> Any:
        idx = self.counters.get(table, 0)
        self.counters[table] = idx + 1
        t = c.type.lower()
        if t == "objectid":
            return self.faker.hexify("^" * 24, upper=False)
        if t == "uuid":
            return self.faker.uuid4()
        if is_int(t):
            return idx + 1
        prefix = (re.sub(r"[^A-Za-z]", "", table)[:3] or "ID").upper()
        return f"{prefix}{101 + idx}"

    def _bump(self, v: Any, attempt: int, c: Optional[Column] = None) -> Any:
        """Vary a value that collided with an earlier one in a UNIQUE column, keeping it valid for the column type."""
        if attempt < 3 or isinstance(v, bool) or v is None:
            return v
        t = c.type.lower() if c else ""
        if c is not None and is_date(t) and isinstance(v, str):
            try:
                d = datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None) + timedelta(days=attempt, minutes=attempt)
            except ValueError:
                return v
            return d.date().isoformat() if t == "date" else d.isoformat(timespec="milliseconds") + "Z"
        if t in {"uuid", "inet", "json", "time", "interval", "bytea", "objectid"} or t.startswith("array:"):
            return v  # formats with structure: a fresh random value is drawn on the next attempt instead
        if isinstance(v, str):
            return f"{v}{attempt}"
        if isinstance(v, int):
            return v + attempt * 7919
        if isinstance(v, float):
            return round(v + attempt * 0.37, 2)
        return v

    def value(self, table: Table, c: Column, use_pool: bool = True) -> Any:
        """A fresh plausible value for one column (used by the repair pass)."""
        self._no_pool = not use_pool
        try:
            v = self._raw(table, c)
        finally:
            self._no_pool = False
        return v[: c.max_length] if isinstance(v, str) and c.max_length else v

    def _from_column(self, table: Table, c: Column) -> Any:
        if c.unique and not c.primary_key:
            return self._uniq(table.name, c, lambda a: self._bump(self._raw(table, c), a, c))
        return self._raw(table, c)

    def _raw(self, table: Table, c: Column) -> Any:
        if c.enum_values:
            return self.pick(c.enum_values)
        t = c.type.lower()
        if self._texty(t):
            hint = self._by_name(table.name, c)
            if hint is not None:
                return hint
        if t in {"boolean", "bool"}:
            return bool(self.rng.random() < (0.9 if c.default == "true" else 0.5))
        if is_int(t):
            return self._numeric(c, True)
        if is_num(t):
            return self._numeric(c, False)
        if t == "date":
            return self._recent(300).date().isoformat()
        if is_date(t):
            return self._recent(300).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if t == "uuid":
            return self.faker.uuid4()
        if t == "json":
            return json.dumps({"key": self.faker.word(), "value": int(self.rng.integers(0, 1000))})
        if t == "inet":
            return self.faker.ipv4()
        if t == "time":
            return self.faker.time()
        if t == "interval":
            return f"{int(self.rng.integers(1, 120))} minutes"
        if t == "bytea":
            return "\\x" + self.faker.hexify("^" * 8, upper=False)
        if t.startswith("array:"):
            inner = Column(name=c.name, type=t[6:], nullable=False, max_length=c.max_length)
            return [self._raw(table, inner) for _ in range(int(self.rng.integers(1, 4)))]
        mx = c.max_length or 60
        return " ".join(self.faker.words(nb=int(self.rng.integers(1, 4))))[:mx]

    def _unique_fk(self, table: str, c: Column, f: Any, pool: list[Row]) -> Any:
        """One-to-one style FK: hand out each parent at most once (random order)."""
        key = (table, c.name)
        state = self._fk_perm.get(key)
        keys = [p[f.ref_column] for p in pool]
        if state is None or state["size"] != len(keys):
            used = state["used"] if state else set()
            todo = [k for k in keys if k not in used]
            order = [todo[i] for i in self.rng.permutation(len(todo))]
            state = {"order": order, "used": used, "size": len(keys), "pos": 0}
            self._fk_perm[key] = state
        if state["pos"] < len(state["order"]):
            k = state["order"][state["pos"]]
            state["pos"] += 1
            state["used"].add(k)
            return k
        return None if c.nullable else (self.pick(keys) if keys else None)

    # ---- rows ----------------------------------------------------------------------------
    def add_row(self, table_name: str, forced: Optional[Row] = None, parents: Optional[dict[str, Row]] = None) -> Row:
        """Build one row; rows that repeat a composite UNIQUE key are rebuilt (up to 250 attempts)."""
        table = self.table_map[table_name]
        groups = [tuple(u) for u in table.unique_together]
        before = self.counters.get(table_name, 0)
        row: Row = {}
        for _ in range(250 if groups else 1):
            self.counters[table_name] = before
            row = self._build(table_name, forced, parents)
            keys = [(g, tuple(str(row.get(c)) for c in g)) for g in groups if all(row.get(c) is not None for c in g)]
            if all(k not in self.composites.get((table_name, g), set()) for g, k in keys):
                break
        for g, k in [(g, tuple(str(row.get(c)) for c in g)) for g in groups if all(row.get(c) is not None for c in g)]:
            self.composites.setdefault((table_name, g), set()).add(k)
        self.dataset.setdefault(table_name, []).append(row)
        return row

    def _build(self, table_name: str, forced: Optional[Row] = None, parents: Optional[dict[str, Row]] = None) -> Row:
        forced, parents = forced or {}, parents or {}
        table = self.table_map[table_name]
        rows = self.dataset.setdefault(table_name, [])
        row: Row = {}
        fk_by_col = {f.column: f for f in table.foreign_keys}
        done: set[str] = set()

        for f in table.foreign_keys:
            p = parents.get(f.ref_table)
            if p and f.column not in forced and f.ref_table != table_name:
                row[f.column] = p[f.ref_column]
                done.add(f.column)

        # Anchor FKs: if parent P references table Q that this table also references, derive Q from P
        for f in table.foreign_keys:
            if f.column in done or f.column in forced or f.ref_table == table_name:
                continue
            ptable = self.table_map.get(f.ref_table)
            prows = self.dataset.get(f.ref_table) or []
            if not ptable or not prows:
                continue
            siblings = [pf for pf in ptable.foreign_keys if any(g is not f and g.ref_table == pf.ref_table for g in table.foreign_keys)]
            if not siblings:
                continue
            parent = self.pick(prows)
            row[f.column] = parent[f.ref_column]
            done.add(f.column)
            for pf in siblings:
                g = next(x for x in table.foreign_keys if x is not f and x.ref_table == pf.ref_table)
                if g.column not in forced and g.column not in done:
                    row[g.column] = parent[pf.column]
                    done.add(g.column)

        for c in table.columns:
            if c.name in forced:
                row[c.name] = forced[c.name]
                continue
            if c.name in done:
                continue
            if c.generated:  # GENERATED ALWAYS AS (expr): the database computes it
                continue
            f = fk_by_col.get(c.name)
            if c.primary_key and not f:
                row[c.name] = self.next_key(table_name, c)
                continue
            if f:
                pool = rows if f.ref_table == table_name else (self.dataset.get(f.ref_table) or [])
                if c.unique and pool and f.ref_table != table_name:
                    row[c.name] = self._unique_fk(table_name, c, f, pool)
                else:
                    row[c.name] = self.pick(pool)[f.ref_column] if pool else None
                continue
            if c.nullable and self.rng.random() < 0.15:
                row[c.name] = None
                continue
            v = self._from_column(table, c)
            row[c.name] = v[: c.max_length] if isinstance(v, str) and c.max_length else v

        self._order_dates(table, row, forced)
        return row

    EARLY = {"start", "starts", "begin", "begins", "from", "opened", "open", "created", "issued", "joined", "registered", "submitted", "ordered", "placed", "scheduled", "booked", "birth", "dob"}
    LATE = {"end", "ends", "until", "to", "closed", "close", "updated", "modified", "expires", "expiry", "expiration", "due", "completed", "finished", "resolved", "deleted", "delivered", "shipped", "reviewed", "approved", "paid", "cancelled", "canceled", "last", "valid"}

    def _order_dates(self, table: Table, row: Row, forced: Row) -> None:
        """Keep 'later' timestamps (end/updated/closed...) on or after 'earlier' ones (start/created/opened...) in the same row."""
        cols = [c for c in table.columns if is_date(c.type) and row.get(c.name) is not None]
        early = [c for c in cols if self._tokens(c.name) & self.EARLY and not self._tokens(c.name) & self.LATE]
        late = [c for c in cols if self._tokens(c.name) & self.LATE and c.name not in forced]
        if not early or not late:
            return

        def parse(v: Any) -> Optional[datetime]:
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None

        floor = max((d for d in (parse(row[c.name]) for c in early) if d), default=None)
        if not floor:
            return
        for c in late:
            cur = parse(row[c.name])
            if cur is None or cur >= floor:
                continue
            nv = floor + timedelta(days=int(self.rng.integers(1, 120)), hours=int(self.rng.integers(0, 24)))
            row[c.name] = nv.date().isoformat() if c.type.lower() == "date" else nv.isoformat(timespec="milliseconds") + "Z"

    def sample_row(self, table_name: str, forced: Optional[Row] = None) -> Row:
        rows = self.dataset.setdefault(table_name, [])
        before = self.counters.get(table_name, 0)
        row = self.add_row(table_name, forced)
        rows.pop()
        self.counters[table_name] = before
        return row

    def pk_of(self, table_name: str, row: Row) -> str:
        pk = next((c for c in self.table_map[table_name].columns if c.primary_key), None)
        return str(row.get(pk.name if pk else "", ""))

    def create_chain(self, table_name: str, forced: Row, depth: int, created: list[dict[str, str]]) -> Row:
        """Create a row plus fresh parents `depth` levels up; deeper ancestors reuse existing rows."""
        table = self.table_map[table_name]
        fks = [f for f in table.foreign_keys if f.ref_table != table_name]
        parents: dict[str, Row] = {}
        anchors = [f for f in fks if any(any(g is not f and g.ref_table == pf.ref_table for g in fks) for pf in self.table_map[f.ref_table].foreign_keys)]
        for f in anchors + [x for x in fks if x not in anchors]:
            if f.ref_table in parents or f.column in forced:
                continue
            pool = self.dataset.get(f.ref_table) or []
            parent = self.create_chain(f.ref_table, {}, max(depth - 1, 0), created) if (depth > 0 or not pool) else self.pick(pool)
            parents[f.ref_table] = parent
            for pf in self.table_map[f.ref_table].foreign_keys:
                sib = next((g for g in fks if g is not f and g.ref_table == pf.ref_table), None)
                if sib and sib.ref_table not in parents:
                    match = next((r for r in self.dataset.get(sib.ref_table, []) if r.get(sib.ref_column) == parent.get(pf.column)), None)
                    if match:
                        parents[sib.ref_table] = match
        row = self.add_row(table_name, forced, parents)
        created.append({"table": table_name, "key": self.pk_of(table_name, row)})
        return row
