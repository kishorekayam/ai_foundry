# app/routers/public.py
"""Public API consumed by the React app (contract: src/api/httpApi.ts)."""
from __future__ import annotations

import logging
import re
import secrets
from typing import Annotated, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response

from .. import ai, jobs, loader, policy, registry, store
from ..auth import require_basic
from ..config import get_settings
from ..engine.exporters import FORMATS, build_export
from ..metadata import adapter
from ..metadata.service import discover_schema
from ..models import (Blueprint, CamelModel, ConnectionRequest, ConnectionResult, Job, JobConfig, LoadJob, LoadPlan, LoadTable, PreviewPage, Schema)
from ..targets import Target, get_target, load_targets, match_target

log = logging.getLogger("atom.api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_basic)])


def client_id(x_client_id: str = Header(default="")) -> Optional[str]:
    """Anonymous per-browser owner of saved connections (swap for real user auth when accounts exist)."""
    if not registry.enabled():
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", x_client_id):
        raise HTTPException(400, "Missing or invalid X-Client-Id header.")
    return x_client_id


Owner = Annotated[Optional[str], Depends(client_id)]


@router.get("/auth/check")
def auth_check(request: Request):
    """Lets the React app verify the Basic credentials it was given (the router already enforced them)."""
    return {"ok": True}


@router.get("/targets")
def targets(owner: Owner):
    return [t.public().model_dump(by_alias=True) for t in load_targets(owner).values()]


@router.delete("/targets/{target_id}")
def delete_target(target_id: str, owner: Owner):
    if not registry.enabled():
        raise HTTPException(405, "Saved connections are managed by the administrator in this mode.")
    if not registry.deactivate(target_id, owner):
        raise HTTPException(404, "Saved connection not found.")
    return {"deleted": target_id}


def _parse_mongo(uri: str):
    u = urlparse(uri or "")
    if u.scheme not in ("mongodb", "mongodb+srv") or not u.hostname:
        return None
    return u.hostname, u.port or 27017, (u.path or "").lstrip("/").split("?")[0], u.scheme == "mongodb+srv"


def _detail(e: Exception) -> str:
    """First line of the driver error, whitespace-collapsed. Driver messages never contain the password."""
    line = (str(e).strip().splitlines() or [""])[0]
    line = re.sub(r"\s+", " ", re.sub(r"\(Background on this error.*", "", line)).strip()
    return line[:220]


def _connect_error(e: Exception) -> str:
    n = e.__class__.__name__.lower() + " " + str(e).lower()
    log.warning("connection test failed: %s: %s", e.__class__.__name__, _detail(e))
    detail = f" Driver said: {_detail(e)}" if _detail(e) else ""
    if "password authentication failed" in n or "authentication failed" in n or "access denied" in n or "authentication" in n and "ssl" not in n:
        return "Authentication failed for the supplied user. Check the username and password." + detail
    if "channel binding" in n:
        return "The server and client could not agree on channel binding. Try SSL mode \"require\"." + detail
    if "does not exist" in n or "unknown database" in n:
        return "The database name was not found on that server." + detail
    if "timeout" in n or "timed out" in n or "could not connect" in n or "connection refused" in n or "serverselection" in n or "can't connect" in n or "name or service not known" in n or "getaddrinfo" in n:
        return "Could not reach the database. Check the host, port and firewall, and that it accepts connections from this server." + detail
    if "ssl" in n or "tls" in n or "certificate" in n:
        return "The secure (TLS/SSL) connection could not be established. Check the SSL setting." + detail
    return "Could not connect with the supplied details." + detail


@router.post("/connections/test", response_model=ConnectionResult, response_model_by_alias=True)
def test_connection(req: ConnectionRequest, owner: Owner):
    def deny(msg: str, database: str = "") -> ConnectionResult:
        return ConnectionResult(ok=False, db_type=req.db_type, database=database or (req.database or ""), metadata_access="Denied", tables_discovered=0, message=msg)

    created: Optional[str] = None
    target: Optional[Target] = None
    if req.target_id:
        target = get_target(req.target_id, owner)
        if not target:
            return deny("Unknown saved connection.")
    elif registry.enabled():
        if req.db_type == "mongodb":
            parsed = _parse_mongo(req.uri or "")
            if not parsed:
                return deny("Enter a valid MongoDB connection URI (mongodb:// or mongodb+srv://).")
            host, port, database, srv = parsed
            if not database:
                return deny("Include the database name in the MongoDB URI (mongodb://host/database).")
            username, password, uri = "", "", req.uri or ""
        else:
            host, port, database, srv = (req.host or "").strip(), req.port, (req.database or "").strip(), False
            username, password, uri = req.username or "", req.password or "", ""
            if not (host and port and database and username):
                return deny("Host, port, database and username are required.")
        if (reason := policy.check_destination(host, port, srv)):
            return deny(reason)
        pg_schema = ""
        if req.db_type == "postgresql":
            pg_schema = (req.db_schema or "public").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,62}", pg_schema):
                return deny("The schema name may only contain letters, digits, _ and $ (max 63 characters).")
        probe = Target(id="", label="", db_type=req.db_type, host=host, port=port or 27017, database=database, load_allowed=False, username=username, password=password, uri=uri, ssl=req.ssl or "prefer", schema=pg_schema or "public")
        try:
            adapter.check_credentials(probe, username, password)
        except Exception as e:
            return deny(_connect_error(e), database)
        assert owner
        existing = registry.find_existing(owner, req.db_type, host, port or 27017, database, username, pg_schema)
        if not existing and registry.count_for_owner(owner) >= get_settings().max_targets_per_owner:
            return deny(f"You can save up to {get_settings().max_targets_per_owner} connections. Remove one first.")
        tid = existing or f"t_{secrets.token_hex(6)}"
        registry.upsert_target(
            tid, (req.label or f"{database} ({host})")[:160], req.db_type, host, port or 27017, database, username, password, uri, req.ssl or "prefer",
            load_allowed=bool(req.allow_load and req.db_type == "postgresql"), owner=owner, schema=pg_schema,
        )
        created = None if existing else tid
        target = get_target(tid, owner)
    else:  # file mode (no registry): destination must equal an approved target
        host, port, db = req.host, req.port, req.database
        if req.db_type == "mongodb":
            parsed = _parse_mongo(req.uri or "")
            host, port, db = (parsed[0], parsed[1], parsed[2]) if parsed else (None, None, None)
        target = match_target(req.db_type, host, port, db)
        if not target:
            return deny("Destination is not on the approved network policy. Use a registered test connection.")
        if req.db_type != "mongodb":
            if not (req.username and req.password):
                return deny("Authentication failed for the supplied user. Check the username and password.")
            try:
                adapter.check_credentials(target, req.username, req.password)
            except Exception:
                return deny("Authentication failed for the supplied user. Check the username and password.", target.database)
    assert target
    if target.db_type != req.db_type:
        return deny("The saved connection is a different database type.", target.database)
    try:
        schema = discover_schema(target)
    except Exception as e:
        if created:
            registry.deactivate(created, owner)
        return deny(f"Could not read metadata: {_friendly(e)}", target.database)
    hint = f' No tables were found in schema "{target.schema}". Check the schema name.' if target.db_type == "postgresql" and not schema.tables else ""
    return ConnectionResult(ok=True, db_type=target.db_type, database=target.database, metadata_access="Allowed", tables_discovered=len(schema.tables), target_id=target.id, message="Connection successful. Metadata-only access confirmed." + hint)  # type: ignore[arg-type]


def _friendly(e: Exception) -> str:
    msg = str(e).splitlines()[0] if str(e) else e.__class__.__name__
    for secret in ("password", "postgresql://", "mongodb://", "mysql+"):
        if secret in msg.lower():
            return "the database or integration service refused the request."
    return msg[:200]


class SchemaRequest(CamelModel):
    target_id: str


@router.post("/schema", response_model=Schema, response_model_by_alias=True)
def schema(req: SchemaRequest, owner: Owner):
    t = get_target(req.target_id, owner)
    if not t:
        raise HTTPException(404, "Saved connection not found.")
    try:
        return discover_schema(t)
    except Exception as e:
        raise HTTPException(502, f"Schema extraction failed: {_friendly(e)}")


@router.post("/plan", response_model=Blueprint, response_model_by_alias=True)
def plan(body: dict):
    sc, cfg = Schema.model_validate(body["schema"]), JobConfig.model_validate(body["config"])
    bp, _ = ai.plan_blueprint(sc, cfg)
    return bp


@router.post("/collection/parse")
def parse_collection(body: dict):
    """Lists the requests found in an uploaded Postman collection / OpenAPI file, matched to tables when a schema is supplied."""
    from ..engine.apisource import match_tables, parse_api_source

    text = body.get("text") or ""
    if len(text) > 8_000_000:
        raise HTTPException(413, "The file is larger than 8 MB.")
    try:
        src = parse_api_source(text)
        if body.get("schema"):
            match_tables(src, Schema.model_validate(body["schema"]))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"Could not read the file: {e.__class__.__name__}")
    return {
        "kind": src.kind, "title": src.title, "baseUrl": src.base_url,
        "endpoints": [{"id": e.key, "method": e.method, "path": e.path, "name": e.name, "folder": e.folder, "table": e.table, "hasBody": e.body is not None} for e in src.endpoints],
    }


@router.post("/jobs")
def create_job(body: dict, owner: Owner):
    try:
        sc, cfg = Schema.model_validate(body["schema"]), JobConfig.model_validate(body["config"])
    except Exception as e:
        raise HTTPException(422, f"Invalid job request: {e}")
    if sc.target_id and not get_target(sc.target_id, owner):
        raise HTTPException(403, "Saved connection not found.")
    return {"jobId": jobs.create_job(sc, cfg, owner)}


def _state(job_id: str):
    st = store.get_job(job_id)
    if not st:
        raise HTTPException(404, "Job not found. Generated datasets may have expired. Please generate again.")
    return st


@router.get("/jobs/{job_id}", response_model=Job, response_model_by_alias=True)
def get_job(job_id: str):
    return _state(job_id).job


@router.get("/jobs/{job_id}/preview", response_model=PreviewPage, response_model_by_alias=True)
def preview(job_id: str, table: str, page: int = Query(0, ge=0), page_size: int = Query(20, ge=1, le=100)):
    st = _state(job_id)
    rows = st.dataset.get(table)
    if rows is None:
        raise HTTPException(404, f"No generated data for table {table}.")
    t = st.schema.table(table)
    chunk = rows[page * page_size : (page + 1) * page_size]
    links: dict[int, list[str]] = {}
    if st.links.get(table) and t:
        pk = next((c.name for c in t.columns if c.primary_key), "")
        for i, r in enumerate(chunk):
            if (l := st.links[table].get(str(r.get(pk)))):
                links[i] = l
    return PreviewPage(table=table, total=len(rows), page=page, page_size=page_size, columns=[c.name for c in t.columns] if t else list(rows[0].keys() if rows else []), rows=chunk, links=links or None)


@router.post("/jobs/{job_id}/generate-missing", response_model=Job, response_model_by_alias=True)
def generate_missing(job_id: str):
    st = _state(job_id)
    if not st.job.report:
        raise HTTPException(409, "Job has not finished.")
    jobs.generate_missing(st)
    return st.job


@router.get("/jobs/{job_id}/export")
def export(job_id: str, format: str):
    st = _state(job_id)
    if format not in FORMATS:
        raise HTTPException(400, f"Unknown export format: {format}")
    if not st.job.report or st.job.report.status == "failed":
        raise HTTPException(409, "Export is disabled until validation passes.")
    if format == "postman" and not st.has_spec:
        raise HTTPException(409, "A Postman collection needs an OpenAPI specification.")
    data, filename, media = build_export(format, st.schema, st.dataset, st.order, st.job.report, st.job.test_cases, st.api_base_url)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Access-Control-Expose-Headers": "Content-Disposition"})


class TargetBody(CamelModel):
    target_id: str
    approved: bool = False


def _plan(st, target_id: str, owner: Optional[str]) -> LoadPlan:
    t = get_target(target_id, owner)
    if not t:
        raise HTTPException(404, "Saved connection not found.")
    return LoadPlan(target=t.public(), tables=[LoadTable(table=n, expected=len(st.dataset[n])) for n in st.order if st.dataset.get(n)])


@router.post("/jobs/{job_id}/load-plan", response_model=LoadPlan, response_model_by_alias=True)
def load_plan(job_id: str, body: TargetBody, owner: Owner):
    return _plan(_state(job_id), body.target_id, owner)


@router.post("/jobs/{job_id}/load")
def start_load(job_id: str, body: TargetBody, owner: Owner):
    st = _state(job_id)
    if not body.approved:
        raise HTTPException(400, "Nothing loads without explicit approval.")
    t = get_target(body.target_id, owner)
    if not t:
        raise HTTPException(404, "Saved connection not found.")
    if not t.load_allowed:
        raise HTTPException(403, "Loading is not enabled for this connection. Reconnect and tick 'allow loading' (PostgreSQL test databases only).")
    if st.schema.target_id and st.schema.target_id != t.id:
        raise HTTPException(403, "Data was generated for a different connection.")
    if not st.job.report or st.job.report.status == "failed":
        raise HTTPException(409, "Load is disabled until validation passes.")
    plan = _plan(st, t.id, owner)
    load_id = f"load_{secrets.token_hex(4)}"
    loader.start_load(load_id, job_id, t.id, [(p.table, p.expected) for p in plan.tables])
    return {"loadId": load_id}


@router.get("/loads/{load_id}", response_model=LoadJob, response_model_by_alias=True)
def get_load(load_id: str):
    l = store.get_load(load_id)
    if not l:
        raise HTTPException(404, "Load job not found.")
    return l
