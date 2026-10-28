# tests/conftest.py
import json
import os
import pathlib
import tempfile
from urllib.parse import urlparse

import pgserver
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def pg():
    d = tempfile.mkdtemp(prefix="atom_pg_")
    srv = pgserver.get_server(d)
    srv.psql("CREATE DATABASE placement_test_db;")
    u = urlparse(srv.get_uri())
    ddl = (ROOT / "scripts" / "seed_placement_db.sql").read_text(encoding="utf-8")
    import psycopg

    with psycopg.connect(f"postgresql://postgres:@{u.hostname}:{u.port}/placement_test_db", autocommit=True) as c:
        c.execute(ddl)
    yield {"host": u.hostname, "port": u.port, "uri": f"postgresql://postgres:@{u.hostname}:{u.port}/placement_test_db"}
    srv.cleanup()


@pytest.fixture(scope="session")
def client(pg, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("atom")
    targets = [{"id": "pg-placement-test", "label": "Placement test DB", "dbType": "postgresql", "host": pg["host"], "port": pg["port"], "database": "placement_test_db", "loadAllowed": True, "usernameEnv": "T_PG_USER", "passwordEnv": "T_PG_PASS", "ssl": "disable"}]
    f = tmp / "targets.json"
    f.write_text(json.dumps(targets))
    os.environ.update({"TARGETS_FILE": str(f), "DATA_DIR": str(tmp / "data"), "T_PG_USER": "postgres", "T_PG_PASS": "", "API_USERNAME": "api_user", "API_PASSWORD": "api_pass-123", "BOOMI_ENABLED": "false", "OPENAI_API_KEY": "", "REGISTRY_DB_URL": "", "MYSQL_HOST": ""})
    from app.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    c.auth = ("api_user", "api_pass-123")
    return c
