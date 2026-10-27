"""Python metadata adapters (metadata only, never table rows).

Used (a) by the /internal/mongo/metadata endpoint that Boomi calls for MongoDB, and
(b) as the development fallback when Boomi is not configured.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text

from ..targets import Target
from .sql import MYSQL_METADATA_SQL, PG_METADATA_SQL


def check_credentials(t: Target, username: str, password: str) -> None:
    """Prove the supplied credentials work (SELECT 1 / ping). Used in memory only, never logged."""
    if t.db_type == "mongodb":
        from pymongo import MongoClient

        client = MongoClient(t.mongo_uri(), serverSelectionTimeoutMS=8000)
        try:
            client.admin.command("ping")
        finally:
            client.close()
        return
    eng = create_engine(t.sqlalchemy_url(username, password), connect_args=_connect_args(t), pool_pre_ping=False)
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    finally:
        eng.dispose()


def _connect_args(t: Target) -> dict[str, Any]:
    """PostgreSQL uses libpq sslmode semantics; MySQL uses verified TLS unless the user chose 'disable'."""
    if t.db_type == "postgresql":
        return {"connect_timeout": 8, "sslmode": {"verify-full": "verify-full"}.get(t.ssl, t.ssl)}
    args: dict[str, Any] = {"connect_timeout": 8}
    if t.ssl != "disable":  # MySQL TLS is always verified against the system CA store
        import ssl

        args["ssl"] = ssl.create_default_context()
    return args


def sql_metadata(t: Target) -> dict[str, Any]:
    eng = create_engine(t.sqlalchemy_url(), connect_args=_connect_args(t))
    try:
        with eng.connect() as c:
            c.execute(text("SET TRANSACTION READ ONLY")) if t.db_type == "postgresql" else None
            if t.db_type == "postgresql":
                row = c.execute(text(PG_METADATA_SQL), {"schema": t.schema}).scalar_one()
            else:
                row = c.execute(text(MYSQL_METADATA_SQL)).scalar_one()
    finally:
        eng.dispose()
    return json.loads(row) if isinstance(row, str) else row


def mongo_metadata(t: Target) -> dict[str, Any]:
    from pymongo import MongoClient

    client = MongoClient(t.mongo_uri(), serverSelectionTimeoutMS=6000)
    try:
        db = client[t.database]
        cols = []
        for info in db.list_collections():
            if info.get("type", "collection") != "collection":
                continue
            validator = (info.get("options") or {}).get("validator")
            cols.append({"name": info["name"], "validator": validator})
        return {"collections": cols}
    finally:
        client.close()
