# app/metadata/normalize.py
"""Turn raw metadata JSON (from the Boomi process or the Python adapter) into the unified Schema model."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..models import Column, ForeignKey, Schema, Table

_INT = {"integer", "int", "int4", "int8", "bigint", "smallint", "int2", "serial", "bigserial", "tinyint", "mediumint"}
_NUM = {"numeric", "decimal", "double precision", "real", "float", "float4", "float8", "double"}


def _base_type(raw: str, udt: str | None, kind: str | None) -> tuple[str, int | None]:
    t = (raw or "").lower()
    max_len = None
    if t.endswith("[]"):
        inner, _ = _base_type(t[:-2], None, None)
        return f"array:{inner}", None
    if t.startswith("json"):
        return "json", None
    if t in ("inet", "cidr"):
        return "inet", None
    if t.startswith("interval"):
        return "interval", None
    if t == "bytea":
        return "bytea", None
    m = re.match(r"(character varying|varchar|character|char)\((\d+)\)", t)
    if m:
        return "varchar", int(m.group(2))
    if kind == "e":
        return "varchar", None
    if t.startswith("timestamp"):
        return "timestamp", None
    if t.startswith("time"):
        return "time", None
    if t.startswith("numeric") or t.startswith("decimal"):
        return "numeric", None
    if t in {"integer", "int4", "int", "int(11)"} or t.startswith("int"):
        return "integer", None
    if t == "boolean" or t == "tinyint(1)":
        return "boolean", None
    if t in {"text", "character varying", "character", "json", "jsonb", "uuid"}:
        return ("uuid" if t == "uuid" else "text"), None
    if t.startswith("enum("):
        return "varchar", None
    if t in {"double precision", "real"} or t.startswith(("double", "float")):
        return "numeric", None
    if t.startswith("varchar"):
        return "varchar", None
    if t in {"date", "datetime"}:
        return ("date" if t == "date" else "timestamp"), None
    if udt in _INT:
        return "integer", None
    return t or "text", max_len


def _enum_from_check(defn: str) -> tuple[str, list[str]] | None:
    """CHECK ((status)::text = ANY (ARRAY['A'::character varying, 'B'::...])) or status IN ('A','B')."""
    m = re.search(r"\(?\(?\"?(\w+)\"?\)?(?:::\w+(?: \w+)?)?\)?\s*(?:=\s*ANY\s*\(\(?ARRAY\[|IN\s*\()(.*?)(?:\]|\))", defn, re.I | re.S)
    if not m:
        return None
    vals = re.findall(r"'((?:[^']|'')*)'", m.group(2))
    return (m.group(1), [v.replace("''", "'") for v in vals]) if vals else None


def _clean_check(defn: str) -> str:
    """CHECK (((a)::numeric >= (0)::numeric) AND (a <= (60)::numeric))  ->  a >= 0 AND a <= 60"""
    body = re.sub(r"^CHECK\s*", "", defn.strip(), flags=re.I)
    body = re.sub(r"::(?:double precision|character varying|bit varying|timestamp with(?:out)? time zone|time with(?:out)? time zone|[a-zA-Z_]+)(?:\(\d+(?:,\s*\d+)?\))?(?:\[\])?", "", body)
    for _ in range(3):
        body = re.sub(r"\(\s*(-?\d+(?:\.\d+)?)\s*\)", r"\g<1>", body)
        body = re.sub(r"\(\s*(\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s*\)", r"\g<1>", body)
    return body.replace('"', "")


def _assign_range_checks(defn: str, cols: dict[str, Column]) -> bool:
    """Attach every single-column comparison in a CHECK to its column. Returns True if anything was understood."""
    body = _clean_check(defn)
    done = False
    for clause in re.split(r"\s+AND\s+", body, flags=re.I):
        clause = clause.strip().strip("()").strip()
        if not re.search(r">=|<=|>|<|BETWEEN", clause, re.I):
            continue
        refs = [n for n in cols if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", clause)]
        if len(refs) == 1:
            c = cols[refs[0]]
            c.check = f"{c.check} AND {clause}" if c.check else clause
            done = True
    return done


def normalize_sql_metadata(raw: dict[str, Any], db_type: str, database: str, target_id: str | None, source: str = "boomi-jdbc", schema_name: str | None = None) -> Schema:
    tables: list[Table] = []
    warnings: list[str] = []
    for t in raw.get("tables", []):
        cols: dict[str, Column] = {}
        pk_cols: list[str] = []
        fks: list[ForeignKey] = []
        unique_together: list[list[str]] = []
        for c in t.get("columns") or []:
            base, max_len = _base_type(c.get("type", ""), c.get("udt"), c.get("typeKind"))
            default = c.get("default")
            serial = bool(c.get("identity")) or (isinstance(default, str) and "nextval(" in default)
            if serial and base == "integer":
                base = "serial"
                default = None
            enum = c.get("enumValues")
            if not enum and (c.get("type") or "").lower().startswith("enum("):
                enum = re.findall(r"'((?:[^']|'')*)'", c["type"])
            pm = re.match(r"(?:numeric|decimal)\((\d+)(?:\s*,\s*(\d+))?\)", (c.get("type") or "").lower())
            cols[c["name"]] = Column(
                precision=int(pm.group(1)) if pm else None,
                scale=int(pm.group(2) or 0) if pm else None,
                name=c["name"],
                type=base,
                max_length=c.get("maxLength") if c.get("maxLength") else max_len,
                nullable=bool(c.get("nullable")),
                enum_values=enum or None,
                default=str(default) if default is not None else None,
                generated=True if c.get("generated") else None,
                identity_always=True if c.get("identityKind") == "a" else None,
            )
            if c.get("generated"):
                cols[c["name"]].nullable = True
        for k in t.get("constraints") or []:
            kcols = k.get("columns") or []
            kind = k.get("type")
            if kind == "p":
                pk_cols = kcols
            elif kind == "u" and len(kcols) == 1 and kcols[0] in cols:
                cols[kcols[0]].unique = True
            elif kind == "u" and len(kcols) > 1 and all(x in cols for x in kcols):
                unique_together.append(list(kcols))
            elif kind == "f":
                ref_schema = k.get("refSchema")
                if schema_name and ref_schema and ref_schema != schema_name:
                    warnings.append(f"{t['name']}.{', '.join(kcols)} references {ref_schema}.{k['refTable']} outside schema \"{schema_name}\". It is treated as a plain column, so loading may fail on that foreign key.")
                    continue
                for a, b in zip(kcols, k.get("refColumns") or []):
                    fks.append(ForeignKey(column=a, ref_table=k["refTable"], ref_column=b))
            elif kind == "c" and k.get("definition"):
                d = k["definition"]
                enum = _enum_from_check(d)
                if enum and enum[0] in cols:
                    cols[enum[0]].enum_values = enum[1]
                else:
                    if not _assign_range_checks(d, cols):
                        warnings.append(f"{t['name']}: check constraint \"{d}\" is not automatically validated.")
        for ix in t.get("uniqueIndexes") or []:  # CREATE UNIQUE INDEX (no constraint object): same rule for the generator
            icols = [x for x in (ix.get("columns") or []) if x in cols]
            if ix.get("expression"):  # columns that only appear inside lower(col), (a || b) ... of the index expression
                icols += [n for n in cols if n not in icols and re.search(rf'(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])', ix['expression'])]
            if ix.get("hasExpression"):
                warnings.append(f"{t['name']}: unique index {ix.get('name')} uses an expression (e.g. lower(col)); its plain columns are treated as unique, case-insensitively.")
            if len(icols) == 1:  # stricter than a partial / expression index, therefore always safe
                cols[icols[0]].unique = True
            elif len(icols) > 1 and icols not in unique_together:
                unique_together.append(icols)
        if len(pk_cols) > 1:  # composite PK: unique as a combination, not column by column
            unique_together.append([x for x in pk_cols if x in cols])
        for p in pk_cols:
            if p in cols:
                cols[p].nullable = False
                if len(pk_cols) == 1:
                    cols[p].primary_key = True
                    cols[p].unique = True
        tables.append(Table(name=t["name"], columns=list(cols.values()), foreign_keys=fks, unique_together=unique_together))
    return Schema(
        db_type=db_type,  # type: ignore[arg-type]
        database=database,
        schema_name=schema_name,
        target_id=target_id,
        tables=tables,
        warnings=warnings,
        source=source,  # type: ignore[arg-type]
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )


def normalize_mongo_metadata(raw: dict[str, Any], database: str, target_id: str | None) -> Schema:
    """raw = {"collections": [{"name":..., "validator": {$jsonSchema} | null, "sampleless": true}]}"""
    tables: list[Table] = []
    warnings = ["MongoDB metadata cannot reveal relationships. Cross-collection references are shown as missing, not guessed."]
    for c in raw.get("collections", []):
        js = (c.get("validator") or {}).get("$jsonSchema")
        cols = [Column(name="_id", type="objectId", primary_key=True, unique=True, nullable=False)]
        if js and js.get("properties"):
            required = set(js.get("required", []))
            for name, p in js["properties"].items():
                if name == "_id":
                    continue
                bt = p.get("bsonType") or p.get("type") or "string"
                bt = bt[0] if isinstance(bt, list) else bt
                cols.append(
                    Column(
                        name=name,
                        type={"int": "int", "long": "int", "double": "double", "decimal": "double", "number": "double", "integer": "int", "bool": "boolean", "boolean": "boolean", "date": "date"}.get(bt, "string"),
                        nullable=name not in required,
                        enum_values=[str(v) for v in p["enum"]] if p.get("enum") else None,
                        max_length=p.get("maxLength"),
                    )
                )
            tables.append(Table(name=c["name"], columns=cols))
        else:
            tables.append(Table(name=c["name"], columns=cols, needs_definition=True))
            warnings.append(f'Collection "{c["name"]}" has no schema validator. Provide a JSON Schema or define its fields manually.')
    return Schema(db_type="mongodb", database=database, target_id=target_id, tables=tables, warnings=warnings, source="boomi-pymongo", extracted_at=datetime.now(timezone.utc).isoformat())
