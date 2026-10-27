"""Endpoints that Boomi calls back into. Protected by the common HTTP Basic credentials (API_USERNAME / API_PASSWORD)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import loader, store
from ..auth import require_basic
from ..metadata import adapter
from ..models import CamelModel
from ..targets import get_target


router = APIRouter(prefix="/internal", dependencies=[Depends(require_basic)])


class MetaReq(CamelModel):
    target_id: str


@router.post("/metadata")
def metadata(body: MetaReq):
    """Boomi Process A: raw metadata JSON for ANY registered target. Python decrypts the credentials from the
    registry; neither Boomi nor the request ever carries them. Reads schema metadata only, never table rows."""
    t = get_target(body.target_id)
    if not t:
        raise HTTPException(404, "Unknown or inactive target.")
    try:
        return adapter.mongo_metadata(t) if t.db_type == "mongodb" else adapter.sql_metadata(t)
    except Exception as e:
        raise HTTPException(502, f"Metadata read failed: {e.__class__.__name__}")


class BatchReq(CamelModel):
    job_id: str
    load_id: str = ""


@router.post("/batch")
def batch(body: BatchReq):
    """Boomi Process B step 4: batch reference + table order (parents first) + row counts. No row data."""
    st = store.get_job(body.job_id)
    if not st:
        raise HTTPException(404, "Unknown job.")
    if load := store.get_load(body.load_id):
        loader.set_step(load, "recv", "done")
        loader.set_step(load, "batch", "done", f"Batch {body.job_id} located")
        loader.set_step(load, "adapter", "running")
    return {"batchRef": body.job_id, "tables": [{"table": t, "rows": len(st.dataset[t])} for t in st.order if st.dataset.get(t)]}


class ExecReq(CamelModel):
    load_id: str
    job_id: str
    target_id: str


@router.post("/load/execute")
def execute(body: ExecReq):
    """Boomi Process B step 6a: the Python database adapter inserts the batch and reports per-table results."""
    load = store.get_load(body.load_id)
    if not load:
        raise HTTPException(404, "Unknown load.")
    loader.set_step(load, "adapter", "done", "Python database adapter selected")
    try:
        res = loader.run_adapter(load, body.job_id, body.target_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        loader.fail(load, str(e))
        return {"status": "ERROR", "perTable": [], "error": str(e)[:300]}
    return {"status": res["status"], "perTable": res["perTable"], "error": load.error}


class LookupReq(CamelModel):
    target_id: str


@router.post("/registry/lookup")
def registry_lookup(body: LookupReq):
    """Boomi Process A/B gate: is this target registered and active, what type is it, may data be loaded into it?
    Answers from the common MySQL registry (non-secret columns only)."""
    t = get_target(body.target_id)
    return {"found": 1 if t else 0, "db_type": t.db_type if t else "", "load_allowed": 1 if (t and t.load_allowed) else 0}


class AuditReq(CamelModel):
    request_id: str
    process_name: str
    status: str
    target_id: str = ""
    message: str = ""


@router.post("/audit")
def audit(body: AuditReq):
    """Boomi writes its execution trail into the common registry database (via this endpoint)."""
    from .. import registry

    if registry.enabled():
        registry.audit(body.request_id, body.process_name, body.status, body.message, body.target_id or None, source="boomi")
    return {"recorded": registry.enabled()}
