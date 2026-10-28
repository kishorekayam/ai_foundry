# app/registry.py
"""Common registry database (MySQL) shared by Python and Boomi.

* registered_targets: the approved test connections. Passwords/URIs are Fernet-encrypted; Boomi reads only the
  non-secret columns (id, db_type, host, port, database_name, load_allowed, active) to validate and route requests.
* boomi_audit: append-only trail written by both sides (request received, metadata read, load result...).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, delete, func, insert, select, update
from sqlalchemy.engine import Engine

from .config import get_settings

log = logging.getLogger("atom.registry")
metadata = MetaData()

registered_targets = Table(
    "registered_targets", metadata,
    Column("id", String(64), primary_key=True),
    Column("owner", String(64), nullable=False, default="shared", index=True),
    Column("label", String(160), nullable=False),
    Column("db_type", String(16), nullable=False),
    Column("host", String(255), nullable=False),
    Column("port", Integer, nullable=False),
    Column("database_name", String(128), nullable=False),
    Column("schema_name", String(128), nullable=True),
    Column("username", String(128), nullable=False, default=""),
    Column("password_enc", Text, nullable=False, default=""),
    Column("uri_enc", Text, nullable=True),
    Column("ssl_mode", String(16), nullable=False, default="prefer"),
    Column("load_allowed", Boolean, nullable=False, default=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("updated_at", DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)),
)

boomi_audit = Table(
    "boomi_audit", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("request_id", String(64), nullable=False),
    Column("source", String(16), nullable=False),  # 'boomi' | 'python'
    Column("process_name", String(64), nullable=False),
    Column("target_id", String(64), nullable=True),
    Column("status", String(24), nullable=False),
    Column("message", Text, nullable=True),
    Column("created_at", DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)),
)


def enabled() -> bool:
    return bool(get_settings().registry_url)


@lru_cache
def engine() -> Engine:
    st = get_settings()
    args: dict[str, Any] = {}
    if st.registry_url.startswith("mysql"):
        args["connect_timeout"] = 15
        if st.registry_ssl_ca:
            args["ssl"] = {"ca": st.registry_ssl_ca}  # verified TLS (Aiven etc.): CA file + hostname check
    return create_engine(st.registry_url, pool_pre_ping=True, pool_recycle=1800, connect_args=args)


def reset_cache() -> None:
    engine.cache_clear()


def _fernet() -> Fernet:
    key = get_settings().registry_key
    if not key:
        raise RuntimeError("REGISTRY_ENCRYPTION_KEY is not set. Generate one with: python scripts/registry_admin.py genkey")
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def decrypt(token: Optional[str]) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Cannot decrypt a registry credential: wrong REGISTRY_ENCRYPTION_KEY") from e


def init_schema() -> None:
    metadata.create_all(engine())
    # create_all never alters an existing table: add columns introduced after the first release
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine()).get_columns("registered_targets")}
    if "schema_name" not in cols:
        with engine().begin() as c:
            c.execute(text("ALTER TABLE registered_targets ADD COLUMN schema_name VARCHAR(128) NULL"))


def list_rows(active_only: bool = True, owner: Optional[str] = None) -> list[dict[str, Any]]:
    q = select(registered_targets)
    if active_only:
        q = q.where(registered_targets.c.active.is_(True))
    if owner is not None:
        q = q.where(registered_targets.c.owner == owner)
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q.order_by(registered_targets.c.id))]


def upsert_target(id: str, label: str, db_type: str, host: str, port: int, database: str, username: str = "", password: str = "", uri: str = "", ssl_mode: str = "prefer", load_allowed: bool = False, owner: str = "shared", schema: str = "") -> None:
    row = dict(
        owner=owner, label=label, db_type=db_type, host=host, port=port, database_name=database, schema_name=schema or None, username=username, password_enc=encrypt(password),
        uri_enc=encrypt(uri) if uri else None, ssl_mode=ssl_mode, load_allowed=load_allowed, active=True, updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    with engine().begin() as c:
        exists = c.execute(select(registered_targets.c.id).where(registered_targets.c.id == id)).first()
        if exists:
            c.execute(update(registered_targets).where(registered_targets.c.id == id).values(**row))
        else:
            c.execute(insert(registered_targets).values(id=id, **row))


def deactivate(id: str, owner: Optional[str] = None) -> bool:
    q = update(registered_targets).where(registered_targets.c.id == id)
    if owner is not None:
        q = q.where(registered_targets.c.owner == owner)
    with engine().begin() as c:
        return c.execute(q.values(active=False)).rowcount > 0


def find_existing(owner: str, db_type: str, host: str, port: int, database: str, username: str, schema: str = "") -> Optional[str]:
    q = select(registered_targets.c.id).where(
        registered_targets.c.owner == owner, registered_targets.c.db_type == db_type, registered_targets.c.host == host,
        registered_targets.c.port == port, registered_targets.c.database_name == database, registered_targets.c.username == username, registered_targets.c.active.is_(True),
        func.coalesce(registered_targets.c.schema_name, "") == (schema or ""))
    with engine().connect() as c:
        r = c.execute(q).first()
    return r[0] if r else None


def count_for_owner(owner: str) -> int:
    return len(list_rows(True, owner))


def audit(request_id: str, process_name: str, status: str, message: str = "", target_id: Optional[str] = None, source: str = "python") -> None:
    """Best-effort: auditing must never break a request."""
    if not enabled():
        return
    try:
        with engine().begin() as c:
            c.execute(insert(boomi_audit).values(request_id=request_id[:64], source=source[:16], process_name=process_name[:64], target_id=target_id, status=status[:24], message=message[:2000]))
    except Exception as e:
        log.warning("audit write failed: %s", e.__class__.__name__)


def recent_audit(request_id: str) -> list[dict[str, Any]]:
    if not enabled():
        return []
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(select(boomi_audit).where(boomi_audit.c.request_id == request_id).order_by(boomi_audit.c.id))]


def purge_audit() -> None:
    with engine().begin() as c:
        c.execute(delete(boomi_audit))
