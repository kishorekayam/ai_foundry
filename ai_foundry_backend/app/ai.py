# app/ai.py
"""Hosted-LLM layer (OpenAI GPT-4o). The model only returns structured JSON; Python validates it against the discovered schema.

The LLM never sees credentials and never executes SQL. If it is unavailable or returns something invalid, the
rule-based planners in engine/planner.py produce the same structures, so every mode keeps working.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from .config import get_settings
from .engine.planner import rule_blueprint
from .models import Blueprint, JobConfig, Scenario, Schema, Table, ValuePool

log = logging.getLogger("atom.ai")


def available() -> bool:
    return bool(get_settings().openai_api_key)


def schema_summary(schema: Schema) -> str:
    """Compact, credential-free description of the schema for prompts."""
    lines = []
    for t in schema.tables:
        cols = []
        for c in t.columns:
            bits = [f"{c.name}:{c.type}"]
            if c.primary_key:
                bits.append("PK")
            if not c.nullable and not c.primary_key:
                bits.append("required")
            if c.unique and not c.primary_key:
                bits.append("unique")
            if c.enum_values:
                bits.append("enum=" + "|".join(c.enum_values))
            if c.check:
                bits.append(f"check={c.check}")
            cols.append(" ".join(bits))
        fks = ", ".join(f"{f.column}->{f.ref_table}.{f.ref_column}" for f in t.foreign_keys)
        lines.append(f"- {t.name}({'; '.join(cols)})" + (f" FKs: {fks}" if fks else ""))
    return "\n".join(lines)


def llm_json(system: str, prompt: str, timeout: float = 60) -> Optional[dict[str, Any]]:
    s = get_settings()
    if not s.openai_api_key:
        return None
    body = {
        "model": s.openai_model,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    try:
        r = httpx.post(f"{s.openai_base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {s.openai_api_key}"}, timeout=timeout)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:  # network, quota, bad JSON: fall back to rules
        log.warning("LLM call failed, using rule-based planner: %s", type(e).__name__)
        return None


BLUEPRINT_SYSTEM = (
    "You design synthetic test-data generation blueprints for a database. Reply with ONE JSON object only, no prose. "
    "Never invent tables or columns; use only those provided. Never include credentials."
)


def plan_blueprint(schema: Schema, config: JobConfig) -> tuple[Blueprint, str]:
    """Returns (blueprint, source) where source is 'ai' or 'rules'."""
    base = rule_blueprint(schema, config)
    text = config.description or ""
    if not available() or not text.strip():
        return base, "rules"
    prompt = f"""Application description / request:
{text}

Database schema:
{schema_summary(schema)}

Return JSON with this shape:
{{
  "domain": "one-sentence domain summary",
  "localeHint": "en_IN | en_US | en_GB | de | fr",
  "scenarios": [{{"table": "...", "column": "...", "value": "ENUM VALUE", "count": 10}}],
  "valuePools": [{{"table": "...", "column": "...", "values": ["realistic domain values (max 25)"]}}],
  "columnRules": [{{"table": "...", "column": "...", "rule": "short rule"}}],
  "notes": ["short caveats"]
}}
Rules: scenarios only for workflow states explicitly requested; "value" must be one of the column's enum values;
valuePools only for free-text columns (not enums, keys or e-mails) where domain-specific values help."""
    raw = llm_json(BLUEPRINT_SYSTEM, prompt)
    if not raw:
        base.notes.append("AI service unavailable, used rule-based interpretation.")
        return base, "rules"
    try:
        ai = Blueprint.model_validate({**raw, "tableCounts": []})
    except ValidationError:
        base.notes.append("AI returned an invalid blueprint, used rule-based interpretation.")
        return base, "rules"
    return _merge_blueprint(schema, base, ai), "ai"


def _merge_blueprint(schema: Schema, base: Blueprint, ai: Blueprint) -> Blueprint:
    notes = list(base.notes)
    seen = {(s.table, s.column, s.value.upper()) for s in base.scenarios}
    scenarios = list(base.scenarios)
    for s in ai.scenarios:
        t = schema.table(s.table)
        if not t:
            notes.append(f'Ignored AI scenario for unknown table "{s.table}".')
            continue
        key = (s.table, s.column, s.value.upper())
        if key not in seen:
            seen.add(key)
            scenarios.append(Scenario(table=s.table, column=s.column, value=s.value.upper(), count=s.count))
    pools: list[ValuePool] = []
    for p in ai.value_pools:
        t = schema.table(p.table)
        c = next((c for c in t.columns if c.name == p.column), None) if t else None
        if not c or c.enum_values or c.primary_key or any(f.column == c.name for f in (t.foreign_keys if t else [])) or c.type.lower() in {"integer", "numeric", "boolean", "date", "timestamp"}:
            continue
        vals = [v[: c.max_length] if c.max_length else v for v in p.values if isinstance(v, str) and v.strip()][:25]
        if vals:
            pools.append(ValuePool(table=p.table, column=p.column, values=vals))
    rules = [r for r in ai.column_rules if (t := schema.table(r.table)) and any(c.name == r.column for c in t.columns)]
    return Blueprint(
        domain=ai.domain or base.domain,
        locale_hint=ai.locale_hint if ai.locale_hint in {"en_IN", "en_US", "en_GB", "de", "fr"} else base.locale_hint,
        table_counts=base.table_counts,
        scenarios=scenarios,
        column_rules=(base.column_rules + rules)[:12],
        value_pools=pools,
        notes=notes + ai.notes[:4],
    )


TESTPLAN_SYSTEM = (
    "You are a senior QA engineer writing API test cases for requests that already exist in the user's collection. "
    "Reply with ONE JSON object only. Refer to endpoints only by the index given and to request fields only by the names given. "
    "Expected behaviour that depends on permissions, duplicate policy or business rules that are not in the schema or the supplied rules MUST set needsRules=true."
)


def plan_extra_cases(endpoints: list[Any], schema: Schema, feature: str, categories: list[str], rules: Optional[str]) -> Optional[dict[str, Any]]:
    """Ask the LLM for cases the rule-based planner cannot know (business rules, domain-specific values). None when unavailable."""
    if not available():
        return None
    lines = []
    for i, e in enumerate(endpoints):
        t = schema.table(e.table) if e.table else None
        fields = ", ".join(f"{k}" for k in (e.body or {})) or "(no body)"
        lines.append(f"[{i}] {e.method} {e.path} fields: {fields}" + (f" | table {t.name}" if t else ""))
    tables = schema_summary(Schema(db_type=schema.db_type, database=schema.database, tables=[t for t in schema.tables if t.name in {e.table for e in endpoints}]))
    prompt = f"""Focus / feature: {feature or '(whole API)'}
Categories wanted: {', '.join(categories)}
Application rules supplied by the user: {rules or '(none)'}
Endpoints from the user's collection:
{chr(10).join(lines)}
Database constraints for the tables behind them:
{tables}

Return JSON: {{"cases": [{{
  "endpoint": 0, "category": "positive|negative|boundary|workflow", "title": "...", "expected": "...",
  "expectedStatus": "2xx|4xx|exact code", "needsRules": false,
  "set": {{"field": "new value"}}, "omit": ["field"], "preconditions": ["..."]
}}]}}
Each case edits the endpoint's example body: "set" changes field values, "omit" removes fields. Use only listed fields.
Add at most 20 cases that go beyond simple required/null/type/length checks: business rules from the supplied rules, realistic domain values, state-dependent behaviour."""
    return llm_json(TESTPLAN_SYSTEM, prompt, timeout=90)
