# scripts/dev_demo.py
"""Run the whole backend against a throw-away embedded PostgreSQL (no install, no credentials needed).

    .venv\\Scripts\\python scripts\\dev_demo.py        # API on http://localhost:8000, Ctrl+C to stop

Creates empty placement_test_db tables from scripts/seed_placement_db.sql. Data is deleted on exit.
"""
import json
import os
import pathlib
import sys
import tempfile
from urllib.parse import urlparse

import pgserver
import psycopg
import uvicorn

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

srv = pgserver.get_server(tempfile.mkdtemp(prefix="atom_demo_pg_"))
srv.psql("CREATE DATABASE placement_test_db;")
u = urlparse(srv.get_uri())
with psycopg.connect(f"postgresql://postgres:@{u.hostname}:{u.port}/placement_test_db", autocommit=True) as c:
    c.execute((ROOT / "scripts" / "seed_placement_db.sql").read_text(encoding="utf-8"))

tmp = pathlib.Path(tempfile.mkdtemp(prefix="atom_demo_"))
targets = [
    {"id": "pg-placement-test", "label": "Placement test DB (PostgreSQL)", "dbType": "postgresql", "host": u.hostname, "port": u.port, "database": "placement_test_db", "loadAllowed": True, "usernameEnv": "DEMO_PG_USER", "passwordEnv": "DEMO_PG_PASS", "ssl": "disable"},
]
(tmp / "targets.json").write_text(json.dumps(targets))
os.environ.update({"TARGETS_FILE": str(tmp / "targets.json"), "DATA_DIR": str(tmp / "data"), "DEMO_PG_USER": "postgres", "DEMO_PG_PASS": "", "MYSQL_HOST": "", "REGISTRY_DB_URL": ""})
os.environ.setdefault("BOOMI_ENABLED", "false")  # set BOOMI_ENABLED=true to route through the deployed Boomi processes
print(f"Embedded PostgreSQL on {u.hostname}:{u.port}. API: http://localhost:8000  (docs at /docs)")
try:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
finally:
    srv.cleanup()
