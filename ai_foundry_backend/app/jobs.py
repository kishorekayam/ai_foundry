# app/jobs.py
"""Generation job runner. Each stage does real work; progress is what the React app polls."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Optional

from . import ai, store
from .engine import pipeline as pl
from .engine.generator import GenContext
from .engine.apisource import match_tables, parse_api_source
from .engine.samples import read_samples
from .engine.tc_planner import Planner, finalize, from_ai
from .engine.tc_validate import run_checks
from .targets import get_target
from .engine.validator import scenario_coverage
from .models import Blueprint, Job, JobConfig, Schema, Stage

log = logging.getLogger("atom.jobs")

STAGES: dict[str, list[tuple[str, str, str]]] = {
    "fast": [
        ("handoff", "Record generation-job handoff", "Boomi"), ("schema", "Validate normalized schema", "Python"),
        ("graph", "Build dependency graph (parents first)", "Python"), ("rows", "Generate parent then child records", "Python"),
        ("validate", "Run nine validation checks", "Python"), ("store", "Store dataset for paginated preview", "Python"),
    ],
    "scenario": [
        ("handoff", "Supply metadata and job context", "Boomi"), ("ai", "AI builds the generation blueprint", "AI"),
        ("bp", "Validate blueprint against schema (Pydantic)", "Python"), ("graph", "Build dependency graph (parents first)", "Python"),
        ("rows", "Generate interconnected records", "Python"), ("scenarios", "Apply scenario rules and verify counts", "Python"),
        ("validate", "Run nine validation checks", "Python"), ("store", "Store dataset for paginated preview", "Python"),
    ],
    "testcase": [
        ("handoff", "Supply metadata and job context", "Boomi"), ("parse", "Read the Postman collection / API specification", "Python"),
        ("match", "Match endpoints to tables and constraints", "Python"), ("sample", "Read sample rows from your database (optional)", "Python"),
        ("ai", "AI adds business-rule test cases", "AI"), ("build", "Build test cases and request fixtures", "Python"),
        ("validate", "Run test-case validation checks", "Python"), ("store", "Store test cases", "Python"),
    ],
}


def create_job(schema: Schema, config: JobConfig, owner: Optional[str] = None) -> str:
    job_id = f"job_{secrets.token_hex(5)}"
    job = Job(id=job_id, config=config, stages=[Stage(id=i, label=l, layer=y) for i, l, y in STAGES[config.mode]])
    st = pl.JobState(job=job, schema=schema, started=time.perf_counter())
    store.put_job(st)
    threading.Thread(target=_run, args=(st, owner), daemon=True, name=job_id).start()
    return job_id


def _run(st: pl.JobState, owner: Optional[str] = None) -> None:
    job = st.job
    cfg = job.config

    def mark(i: int, state: str, detail: Optional[str] = None) -> None:
        job.stages[i] = job.stages[i].model_copy(update={"state": state, "detail": detail})

    src = None
    planner: Optional[Planner] = None
    cases: list = []
    samples: dict = {}
    try:
        for i, stage in enumerate(job.stages):
            mark(i, "running")
            time.sleep(0.2)
            sid, detail = stage.id, None
            if sid == "handoff":
                detail = f"Job {job.id} registered with {len(st.schema.tables)} tables of metadata"
            elif sid == "ai" and cfg.mode == "scenario":
                bp, src = ai.plan_blueprint(st.schema, cfg)
                job.blueprint, st.ai_source = bp, src
                detail = "Blueprint returned by the hosted LLM" if src == "ai" else "AI unavailable, rule-based interpretation used"
            elif sid == "bp":
                bp = job.blueprint
                assert bp
                detail = f"{len(bp.scenarios)} scenario(s), {len(bp.table_counts)} table count(s), {len(bp.value_pools)} value pool(s) accepted"
            elif sid == "rows":
                counts = [(t.table, t.count) for t in (job.blueprint.table_counts if cfg.mode == "scenario" and job.blueprint else cfg.tables)]
                pl.generate_tables(st, counts, job.blueprint)
                detail = f"{sum(len(r) for r in st.dataset.values())} records created"
            elif sid == "scenarios":
                pl.refresh_coverage(st)
                detail = f"{sum(1 for c in (st.coverage or []) if c.result == 'Covered')}/{len(st.coverage or [])} covered"
            elif sid == "parse":
                tc = cfg.test_case
                assert tc
                text = tc.collection_text or tc.open_api_text
                if not (text or "").strip():
                    raise ValueError("Add a Postman collection or an OpenAPI file. Test cases are written against its real endpoints.")
                src = parse_api_source(text)
                st.api_base_url, st.has_spec = tc.api_base_url or src.base_url or None, True
                detail = f"{len(src.endpoints)} requests found in the {'Postman collection' if src.kind == 'postman' else 'OpenAPI file'}"
            elif sid == "match":
                assert src
                match_tables(src, st.schema)
                n = sum(1 for e in src.endpoints if e.table)
                detail = f"{n} of {len(src.endpoints)} requests matched to a table"
            elif sid == "sample":
                tc = cfg.test_case
                assert tc and src
                if tc.use_db_samples and st.schema.target_id:
                    target = get_target(st.schema.target_id, owner)
                    if not target:
                        raise ValueError("The saved connection for row sampling was not found.")
                    wanted = sorted({e.table for e in src.endpoints if e.table and (not tc.selected_endpoints or e.key in tc.selected_endpoints)})
                    samples, notes = read_samples(target, wanted)
                    st.adjustments.extend(notes)
                    detail = f"{sum(len(v) for v in samples.values())} existing rows read from {len([v for v in samples.values() if v])} table(s)"
                else:
                    detail = "Skipped: values come from your collection"
            elif sid == "ai":
                tc = cfg.test_case
                assert tc and src
                rules = bool((tc.business_rules or "").strip())
                planner = Planner(src, st.schema, list(tc.categories), samples, rules_supplied=rules)
                cases = planner.plan(tc.selected_endpoints or None)
                chosen = [e for e in src.endpoints if not tc.selected_endpoints or e.key in tc.selected_endpoints]
                raw = ai.plan_extra_cases(chosen, st.schema, tc.feature, list(tc.categories), tc.business_rules)
                st.ai_source = "ai" if raw else "rules"
                extra = from_ai(raw, planner, chosen) if raw else []
                cases += extra
                detail = f"{len(extra)} extra case(s) from the AI" if raw else "AI unavailable: rule-based cases only"
            elif sid == "build":
                job.test_cases = finalize(cases)
                if not job.test_cases:
                    raise ValueError("No test cases could be built from the selected requests and categories.")
                detail = f"{len(job.test_cases)} test cases for {len({c.endpoint for c in job.test_cases})} request(s). No records are written to your database."
            elif sid == "validate" and cfg.mode == "testcase":
                assert src and job.test_cases is not None and cfg.test_case
                st.tc_checks = run_checks(st.schema, src, job.test_cases, list(cfg.test_case.categories), {t: len(r) for t, r in samples.items() if r})
                job.report = pl.build_report(st, int((time.perf_counter() - st.started) * 1000))
                detail = f"{sum(1 for c in job.report.checks if c.status == 'passed')} of {len(job.report.checks)} passed"
            elif sid == "validate":
                pl.finalize_unsupported(st)
                job.report = pl.build_report(st, int((time.perf_counter() - st.started) * 1000))
                detail = f"{sum(1 for c in job.report.checks if c.status == 'passed')} passed"
            elif sid == "store":
                store.save_job(st)
                detail = "Dataset stored"
            mark(i, "done", detail)
        assert job.report
        job.status = job.report.status
        store.save_job(st)
    except Exception as e:  # surface the real reason to the UI
        log.exception("job %s failed", job.id)
        for i, s in enumerate(job.stages):
            if s.state == "running":
                mark(i, "failed", str(e))
        job.error = str(e)
        job.status = "failed"


def generate_missing(st: pl.JobState) -> None:
    ctx = st.ctx or pl.restore_context(st)
    for cov in st.coverage or []:
        if cov.result not in ("Missing", "Partial"):
            continue
        s = cov.scenario
        t = st.schema.table(s.table)
        assert t
        if any(f.ref_table != t.name and not st.dataset.get(f.ref_table) for f in t.foreign_keys):
            continue
        for _ in range(s.count - cov.generated):
            ctx.add_row(s.table, {s.column: s.value})
        st.requested[s.table] = max(st.requested.get(s.table, 0), len(st.dataset[s.table]))
    pl.refresh_coverage(st)
    st.adjustments = [a for a in st.adjustments if not a.startswith("Scenario")]
    if st.job.blueprint:
        st.job.blueprint.notes = [n for n in st.job.blueprint.notes if not n.startswith("Scenario total")]
    st.job.report = pl.build_report(st, st.job.report.duration_ms if st.job.report else 0)
    st.job.status = st.job.report.status
    store.save_job(st)
