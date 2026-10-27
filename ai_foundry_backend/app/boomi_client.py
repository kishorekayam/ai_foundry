"""Calls the Boomi processes (Web Services Server listeners). Requests carry a target id, never credentials."""
from __future__ import annotations

import uuid
from typing import Any

import httpx

from .config import get_settings


class BoomiError(RuntimeError):
    pass


def configured() -> bool:
    s = get_settings()
    return s.boomi_enabled and bool(s.boomi_base_url)


def _post(path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    s = get_settings()
    # Always present the common API credentials; a runtime listener port set to "none" simply ignores them.
    auth = (s.boomi_username, s.boomi_token) if s.boomi_auth_type != "bearer" and s.boomi_username else None
    headers = {"Authorization": f"Bearer {s.boomi_bearer}"} if s.boomi_auth_type == "bearer" and s.boomi_bearer else {}
    try:
        r = httpx.post(f"{s.boomi_base_url}{path}", json=body, auth=auth, headers=headers, timeout=timeout, verify=s.boomi_verify_ssl)
    except httpx.HTTPError as e:
        raise BoomiError(f"Boomi is unreachable: {e}") from e
    if r.status_code >= 400:
        raise BoomiError(f"Boomi returned HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError as e:
        raise BoomiError("Boomi returned a non-JSON response") from e


def run_metadata_process(target_id: str, db_type: str, request_id: str | None = None) -> dict[str, Any]:
    """Boomi Process A. Returns raw metadata JSON (SQL: {'tables':[...]}; MongoDB: {'collections':[...]})."""
    s = get_settings()
    return _post(s.boomi_metadata_path, {"requestId": request_id or uuid.uuid4().hex[:12], "targetId": target_id, "dbType": db_type}, timeout=90)


def run_load_process(load_id: str, job_id: str, target_id: str) -> dict[str, Any]:
    """Boomi Process B. Boomi calls back /internal/jobs/{job}/batch and /internal/load/execute."""
    s = get_settings()
    return _post(s.boomi_load_path, {"loadId": load_id, "jobId": job_id, "targetId": target_id}, timeout=600)
