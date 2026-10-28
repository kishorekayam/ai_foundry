# app/engine/planner.py
"""Rule-based planners. They produce the same structures the LLM must return, so the pipeline is identical
whether the plan comes from Gemini or from these rules (used when the AI service is unavailable)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from ..models import Blueprint, ColumnRule, JobConfig, Scenario, Schema, Table, TableCount
from .generator import GenContext, is_date, is_int, is_num, is_text, parse_range

CELL = Any


def _singular(w: str) -> str:
    return w[:-3] + "y" if w.endswith("ies") else (w[:-1] if w.endswith("s") else w)


def _words(s: str) -> str:
    return s.lower().replace("_", " ")


def aliases(t: Table) -> list[str]:
    parts = _words(t.name).split(" ")
    out: set[str] = set()
    for i in range(len(parts)):
        tail = parts[i:]
        out.add(" ".join(tail))
        out.add(" ".join(tail[:-1] + [_singular(tail[-1])]))
    return sorted(out, key=len, reverse=True)


def find_table(schema: Schema, text: str) -> Optional[tuple[Table, str]]:
    t = _words(text).strip()
    for table in schema.tables:
        for a in aliases(table):
            if t.endswith(a):
                return table, t[: len(t) - len(a)].strip()
    return None


def rule_blueprint(schema: Schema, config: JobConfig) -> Blueprint:
    text = config.description or ""
    notes: list[str] = []
    counts = {t.table: t.count for t in config.tables}
    scenarios = list(config.scenarios or [])
    for clause in [c.strip() for c in re.split(r"[,;\n]|\band\b|\.(?=\s|$)", text, flags=re.I) if c and c.strip()]:
        m = re.search(r"(?:generate|create|add|include|with)?\s*(\d[\d,]*)\s+(.+)$", clause, re.I)
        if not m:
            continue
        n = int(m.group(1).replace(",", ""))
        hit = find_table(schema, m.group(2))
        if not hit:
            continue
        table, rest = hit
        if not rest:
            counts[table.name] = n
            continue
        state = rest.split(" ")[-1].upper()
        col = next((c for c in table.columns if c.enum_values and any(v.upper() == state for v in c.enum_values)), None) or next((c for c in table.columns if c.name == "status"), None)
        scenarios.append(Scenario(table=table.name, column=col.name if col else "status", value=state, count=n))
    domain = text.strip() or "Generic application (no description supplied)"
    locale_hint = "en_IN" if re.search(r"india", text, re.I) else "en_GB" if re.search(r"\b(uk|british|england)\b", text, re.I) else config.locale
    rules = [ColumnRule(table=t.name, column=c.name, rule=f"Weighted choice over {' / '.join(c.enum_values)}") for t in schema.tables for c in t.columns if c.enum_values and not c.primary_key][:8]
    email_cols = [f"{t.name}.{c.name}" for t in schema.tables for c in t.columns if "email" in c.name]
    if email_cols:
        notes.append(f"Locale-appropriate unique e-mail addresses for {', '.join(email_cols[:3])}{'…' if len(email_cols) > 3 else ''}")
    per_table: dict[str, int] = {}
    for s in scenarios:
        per_table[s.table] = per_table.get(s.table, 0) + s.count
    for table, total in per_table.items():
        have = counts.get(table, 0)
        if have and total > have:
            notes.append(f"Scenario total for {table} ({total}) exceeds the requested record count ({have}); some scenarios will be reported as missing.")
    if not text.strip():
        notes.append("No application description given, so only scenarios and counts were applied.")
    return Blueprint(domain=domain, locale_hint=locale_hint, table_counts=[TableCount(table=k, count=v) for k, v in counts.items()], scenarios=scenarios, column_rules=rules, notes=notes)
