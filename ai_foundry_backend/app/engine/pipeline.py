"""Generation pipeline: schema -> rules -> dependency graph -> parents -> children -> scenarios -> validate."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..models import Blueprint, Job, JobConfig, Report, ScenarioCoverage, Schema, TestCaseCoverage, PerTable, ValidationCheck
from .generator import Dataset, GenContext, Row, coerce_value, dependency_order, required_parents
from .repair import repair_dataset
from .validator import scenario_coverage, unsupported_constraints, validate


@dataclass
class JobState:
    job: Job
    schema: Schema
    dataset: Dataset = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    links: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    coverage: Optional[list[ScenarioCoverage]] = None
    adjustments: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    requested: dict[str, int] = field(default_factory=dict)
    started: float = 0.0
    api_base_url: Optional[str] = None
    has_spec: bool = False
    ctx: Optional[GenContext] = None
    ai_source: str = "rules"
    tc_checks: list[ValidationCheck] = field(default_factory=list)  # Mode 3: checks computed by tc_validate
    batch_ref: str = ""


def pools_from(bp: Optional[Blueprint]) -> dict[tuple[str, str], list[str]]:
    return {(p.table, p.column): p.values for p in (bp.value_pools if bp else [])}


def generate_tables(st: JobState, counts: list[tuple[str, int]], bp: Optional[Blueprint]) -> None:
    schema, cfg = st.schema, st.job.config
    ctx = GenContext(schema, bp.locale_hint if bp else cfg.locale, cfg.seed, (bp.domain if bp else cfg.description), pools_from(bp))
    st.ctx = ctx
    want = {t: n for t, n in counts if n > 0}
    selected = set(want)
    for p in required_parents(schema, selected):
        want[p] = 5
        st.adjustments.append(f'Added parent table "{p}" with 5 records because a selected table has a required foreign key to it.')
    requested_by_user = dict(counts)
    for k, v in want.items():
        st.requested[k] = requested_by_user.get(k, v)
    order, cyclic, self_refs = dependency_order(schema, selected)
    for t in cyclic:
        st.unsupported.append(f"{t}: part of a cyclic relationship. Skipped instead of bypassing constraints.")
    for t in self_refs:
        st.unsupported.append(f"{t}: self-reference handled by leaving the first record's parent null.")
    st.order = order

    # Feasibility: unique columns limited by enum size or by a 1:1 parent
    for name in order:
        t = schema.table(name)
        assert t
        n = want[name]
        for col in t.columns:
            if col.unique and not col.primary_key and col.enum_values and n > len(col.enum_values):
                st.adjustments.append(f'{name}: {n} records impossible, unique column "{col.name}" only has {len(col.enum_values)} permitted values. Proposed {len(col.enum_values)}.')
                n = len(col.enum_values)
            fk = next((f for f in t.foreign_keys if f.column == col.name), None)
            if col.unique and fk and want.get(fk.ref_table, 0) < n:
                st.adjustments.append(f'{name}: unique foreign key "{col.name}" needs {n} distinct {fk.ref_table} records, only {want.get(fk.ref_table, 0)} exist. Proposed {want.get(fk.ref_table, 0)}.')
                n = want.get(fk.ref_table, 0)
        fk_cols = {f.column: f for f in t.foreign_keys}
        for ut in t.unique_together:  # composite UNIQUE over foreign keys: at most (parents x parents) distinct pairs
            if ut and all(c in fk_cols for c in ut):
                combos = 1
                for ref in {fk_cols[c].ref_table for c in ut}:
                    combos *= max(1, want.get(ref, len(ctx.dataset.get(ref, [])) or 1))
                if n > combos:
                    st.adjustments.append(f'{name}: unique combination ({", ".join(ut)}) allows only {combos} distinct rows with the available parent records. Proposed {combos}.')
                    n = combos
        want[name] = n

    # Scenario slot allocation: exact status counts, remaining rows get the non-requested values
    forced_by: dict[str, list[Row]] = {n: [{} for _ in range(want[n])] for n in order}
    groups: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for s in (bp.scenarios if bp else []):
        t = schema.table(s.table)
        col = next((c for c in t.columns if c.name == s.column), None) if t else None
        if s.table not in want or not col or (col.enum_values and s.value not in col.enum_values):
            continue
        groups.setdefault((s.table, s.column), []).append((s.value, s.count))
    for (table, column), items in groups.items():
        slots = list(ctx.rng.permutation(len(forced_by[table])))
        cursor = 0
        col = next(c for c in schema.table(table).columns if c.name == column)  # type: ignore[union-attr]
        for value, count in items:
            for _ in range(count):
                if cursor >= len(slots):
                    break
                forced_by[table][int(slots[cursor])][column] = coerce_value(col, value)
                cursor += 1
        others = [v for v in (col.enum_values or []) if all(v != i[0] for i in items)]
        pool = others or (col.enum_values or [])
        if col.type.lower() in {"boolean", "bool"} and len(items) == 1:
            pool = [not coerce_value(col, items[0][0])]  # every other row gets the opposite value, so the count is exact
        if pool:
            for f in forced_by[table]:
                f.setdefault(column, ctx.pick(pool))

    for name in order:
        t = schema.table(name)
        assert t
        for forced in forced_by[name]:
            self_fk = next((f for f in t.foreign_keys if f.ref_table == name), None)
            if self_fk and not ctx.dataset.get(name):
                ctx.add_row(name, {self_fk.column: None, **forced})
            else:
                ctx.add_row(name, forced)
        ctx.dataset.setdefault(name, [])
    st.dataset = ctx.dataset
    st.adjustments.extend(repair_dataset(schema, ctx, order))


def restore_context(st: JobState) -> GenContext:
    """Rebuild a generation context for a job loaded from disk (used by generate-missing)."""
    cfg = st.job.config
    bp = st.job.blueprint
    ctx = GenContext(st.schema, bp.locale_hint if bp else cfg.locale, (cfg.seed or 0) + sum(len(r) for r in st.dataset.values()), (bp.domain if bp else cfg.description), pools_from(bp))
    ctx.dataset = st.dataset
    for t in st.schema.tables:
        rows = st.dataset.get(t.name, [])
        ctx.counters[t.name] = len(rows)
        for c in t.columns:
            if c.unique and not c.primary_key:
                ctx.uniques[f"{t.name}.{c.name}"] = {str(r.get(c.name)) for r in rows}
    st.ctx = ctx
    return ctx


def build_report(st: JobState, duration_ms: int) -> Report:
    job = st.job
    checks = st.tc_checks if job.config.mode == "testcase" else validate(st.schema, st.dataset, st.coverage, job.test_cases)
    by_id = {c.id: c for c in checks}

    def pct(i: str) -> float:
        k = by_id.get(i)
        return round((k.checked - k.failed) / k.checked * 1000) / 10 if k and k.checked else 100.0

    per_table = [PerTable(table=t, requested=st.requested.get(t, len(r)), generated=len(r)) for t, r in st.dataset.items()]
    # Mode 3 only writes test cases (no data is loaded), so its checks are advice and never block export.
    failed = any(c.status == "failed" for c in checks) and job.config.mode != "testcase"
    if job.config.mode == "testcase":
        checks = [c.model_copy(update={"status": "warning"}) if c.status == "failed" else c for c in checks]
    warn = any(c.status == "warning" for c in checks) or bool(st.adjustments)
    tc = job.test_cases
    cov: Optional[TestCaseCoverage] = None
    if tc is not None:
        cov = TestCaseCoverage(
            by_category={k: sum(1 for t in tc if t.category == k) for k in ("positive", "negative", "boundary", "workflow")},
            total=len(tc), with_prerequisites=sum(1 for t in tc if t.prerequisite_records), ready_to_export=sum(1 for t in tc if t.ready), needing_rules=sum(1 for t in tc if t.needs_rules and not t.ready),
        )
    return Report(
        job_id=job.id, db_type=st.schema.db_type, database=st.schema.database, tables_discovered=len(st.schema.tables), mode=job.config.mode,
        records_requested=sum(p.requested for p in per_table), records_generated=sum(p.generated for p in per_table),
        data_type_validity=pct("type"), relationship_integrity=pct("fk"), uniqueness_violations=(by_id["unique"].failed + by_id["pk"].failed) if "unique" in by_id else 0,
        status="failed" if failed else ("partial" if warn else "completed"), duration_ms=duration_ms,
        unsupported_constraints=st.unsupported, adjustments=st.adjustments, checks=checks, per_table=per_table, scenario_coverage=st.coverage, test_coverage=cov,
    )


def refresh_coverage(st: JobState) -> None:
    bp = st.job.blueprint
    st.coverage = scenario_coverage(st.dataset, st.schema, bp.scenarios if bp else [])


def finalize_unsupported(st: JobState) -> None:
    st.unsupported = list(dict.fromkeys(st.unsupported + unsupported_constraints(st.schema)))
