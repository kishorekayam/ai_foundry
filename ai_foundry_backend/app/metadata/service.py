"""Schema discovery orchestration: Boomi Process A when configured, otherwise the Python adapter directly."""
from __future__ import annotations

import uuid

from .. import boomi_client, registry
from ..models import Schema
from ..targets import Target
from . import adapter
from .normalize import normalize_mongo_metadata, normalize_sql_metadata


def discover_schema(t: Target) -> Schema:
    via_boomi = boomi_client.configured()
    rid = uuid.uuid4().hex[:12]
    registry.audit(rid, "metadata", "REQUESTED", "via Boomi Process A" if via_boomi else "direct Python adapter", t.id)
    try:
        if via_boomi:
            raw = boomi_client.run_metadata_process(t.id, t.db_type, rid)
        else:
            raw = adapter.mongo_metadata(t) if t.db_type == "mongodb" else adapter.sql_metadata(t)
    except Exception as e:
        registry.audit(rid, "metadata", "FAILED", e.__class__.__name__, t.id)
        raise
    registry.audit(rid, "metadata", "COMPLETE", "", t.id)
    if t.db_type == "mongodb":
        schema = normalize_mongo_metadata(raw, t.database, t.id)
    else:
        schema = normalize_sql_metadata(raw, t.db_type, t.database, t.id, "boomi-jdbc", t.schema if t.db_type == "postgresql" else None)
    if not via_boomi:
        schema.warnings.insert(0, "Development mode: Boomi is not configured, so metadata was read directly by the Python adapter.")
    return schema
