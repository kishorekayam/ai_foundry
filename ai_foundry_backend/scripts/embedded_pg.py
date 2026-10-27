"""Throw-away PostgreSQL with the empty placement_test_db schema, to use as a *user database* while the API runs
against the real Aiven MySQL registry.

    python scripts\\embedded_pg.py        # prints host/port/user to type into the UI; Ctrl+C removes everything
"""
import pathlib
import tempfile
import time
from urllib.parse import urlparse

import pgserver
import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent
srv = pgserver.get_server(tempfile.mkdtemp(prefix="atom_userdb_"))
srv.psql("CREATE DATABASE placement_test_db;")
u = urlparse(srv.get_uri())
with psycopg.connect(f"postgresql://postgres:@{u.hostname}:{u.port}/placement_test_db", autocommit=True) as c:
    c.execute((ROOT / "scripts" / "seed_placement_db.sql").read_text(encoding="utf-8"))
print("\nTest database is ready. Enter this in the UI (New connection, PostgreSQL):")
print(f"  Host: {u.hostname}   Port: {u.port}   Database: placement_test_db   Username: postgres   Password: (leave empty)   SSL: disable")
print("  Tick 'disposable test database, allow loading'. Needs ALLOW_PRIVATE_TARGETS=true on the API.")
print("Press Ctrl+C to stop and delete it.\n")
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
finally:
    srv.cleanup()
