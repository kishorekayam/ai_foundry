# app/targets.py
"""Approved test connections.

Source of truth is the MySQL registry (shared with Boomi) when REGISTRY_DB_URL / MYSQL_* is configured; otherwise
a local targets.json whose secrets come from environment variables (development / tests).
Credentials never reach the browser, the AI prompts or the logs.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import quote_plus

from . import registry
from .config import get_settings
from .models import ApprovedTarget


@dataclass
class Target:
    id: str
    label: str
    db_type: str
    host: str
    port: int
    database: str
    load_allowed: bool
    username: str = ""
    password: str = ""
    uri: str = ""
    ssl: str = "prefer"
    owner: str = "shared"
    schema: str = "public"  # PostgreSQL schema to read from and load into

    def public(self) -> ApprovedTarget:
        return ApprovedTarget(id=self.id, label=self.label, db_type=self.db_type, host=self.host, port=self.port, database=self.database, load_allowed=self.load_allowed, schema_name=self.schema if self.db_type == "postgresql" else None)  # type: ignore[arg-type]

    def sqlalchemy_url(self, username: str | None = None, password: str | None = None) -> str:
        user = quote_plus(username if username is not None else self.username)
        pw = quote_plus(password if password is not None else self.password)
        driver = {"postgresql": "postgresql+psycopg", "mysql": "mysql+pymysql"}[self.db_type]
        return f"{driver}://{user}:{pw}@{self.host}:{self.port}/{self.database}"

    def mongo_uri(self) -> str:
        if self.uri:
            return self.uri
        auth = f"{quote_plus(self.username)}:{quote_plus(self.password)}@" if self.username else ""
        return f"mongodb://{auth}{self.host}:{self.port}/{self.database}"


def _from_registry(owner: str | None = None) -> dict[str, Target]:
    out: dict[str, Target] = {}
    for r in registry.list_rows(active_only=True, owner=owner):
        out[r["id"]] = Target(
            id=r["id"], label=r["label"], db_type=r["db_type"], host=r["host"], port=int(r["port"]), database=r["database_name"],
            load_allowed=bool(r["load_allowed"]), username=r["username"] or "", password=registry.decrypt(r["password_enc"]),
            uri=registry.decrypt(r["uri_enc"]), ssl=r["ssl_mode"] or "prefer", owner=r["owner"], schema=r.get("schema_name") or "public",
        )
    return out


def _from_file() -> dict[str, Target]:
    f = get_settings().targets_file
    if not f.exists():
        return {}
    out: dict[str, Target] = {}
    for t in json.loads(f.read_text(encoding="utf-8")):
        env = os.environ.get
        out[t["id"]] = Target(
            id=t["id"], label=t["label"], db_type=t["dbType"], host=t["host"], port=int(t["port"]), database=t["database"],
            load_allowed=bool(t.get("loadAllowed", False)), username=env(t.get("usernameEnv", ""), ""), password=env(t.get("passwordEnv", ""), ""),
            uri=env(t.get("uriEnv", ""), "") if t.get("uriEnv") else "", ssl=t.get("ssl", "prefer"), schema=t.get("schema", "public"),
        )
    return out


def load_targets(owner: str | None = None) -> dict[str, Target]:
    """owner=None returns everything (trusted internal callers); a client id returns only that client's saved connections."""
    return _from_registry(owner) if registry.enabled() else _from_file()


def get_target(target_id: str, owner: str | None = None) -> Target | None:
    return load_targets(owner).get(target_id)


def match_target(db_type: str, host: str | None, port: int | None, database: str | None) -> Target | None:
    """Policy check for manually entered destinations: must equal an approved target exactly."""
    for t in load_targets().values():
        if t.db_type == db_type and t.host == (host or "").strip() and t.port == port and t.database == (database or "").strip():
            return t
    return None
