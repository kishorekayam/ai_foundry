# app/store.py
"""Job and load stores: in memory, mirrored to JSON files so a restart (e.g. Render free tier sleeping) keeps datasets."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from .config import get_settings
from .engine.pipeline import JobState
from .models import Job, LoadJob, ScenarioCoverage, Schema

_lock = threading.RLock()
_jobs: dict[str, JobState] = {}
_loads: dict[str, LoadJob] = {}


def _dir(kind: str) -> Path:
    d = get_settings().data_dir / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def put_job(st: JobState) -> None:
    with _lock:
        _jobs[st.job.id] = st


def save_job(st: JobState) -> None:
    payload = {
        "job": st.job.model_dump(by_alias=True, mode="json"),
        "schema": st.schema.model_dump(by_alias=True, mode="json"),
        "dataset": st.dataset, "order": st.order, "links": st.links,
        "coverage": [c.model_dump(by_alias=True, mode="json") for c in st.coverage] if st.coverage is not None else None,
        "adjustments": st.adjustments, "unsupported": st.unsupported, "requested": st.requested,
        "apiBaseUrl": st.api_base_url, "hasSpec": st.has_spec, "aiSource": st.ai_source,
    }
    (_dir("jobs") / f"{st.job.id}.json").write_text(json.dumps(payload, default=str), encoding="utf-8")


def get_job(job_id: str) -> Optional[JobState]:
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    f = _dir("jobs") / f"{job_id}.json"
    if not f.exists() or not job_id.replace("_", "").isalnum():
        return None
    p = json.loads(f.read_text(encoding="utf-8"))
    st = JobState(
        job=Job.model_validate(p["job"]), schema=Schema.model_validate(p["schema"]), dataset=p["dataset"], order=p["order"], links=p["links"],
        coverage=[ScenarioCoverage.model_validate(c) for c in p["coverage"]] if p["coverage"] is not None else None,
        adjustments=p["adjustments"], unsupported=p["unsupported"], requested=p["requested"], api_base_url=p.get("apiBaseUrl"), has_spec=p.get("hasSpec", False), ai_source=p.get("aiSource", "rules"),
    )
    put_job(st)
    return st


def put_load(l: LoadJob) -> None:
    with _lock:
        _loads[l.id] = l


def get_load(load_id: str) -> Optional[LoadJob]:
    with _lock:
        return _loads.get(load_id)


def lock() -> threading.RLock:
    return _lock
