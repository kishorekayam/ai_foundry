# scripts/seed_placement_db.py
"""Create placement_test_db (empty tables) and its least-privilege user on an existing PostgreSQL server.

    set PGADMIN_URL=postgresql+psycopg://postgres:<admin-password>@localhost:5432/postgres
    set PG_PLACEMENT_PASSWORD=<password for the app user>
    python scripts/seed_placement_db.py
"""
import os
import pathlib
import sys

from sqlalchemy import create_engine, text

admin = os.environ.get("PGADMIN_URL")
pw = os.environ.get("PG_PLACEMENT_PASSWORD")
if not admin or not pw:
    sys.exit("Set PGADMIN_URL and PG_PLACEMENT_PASSWORD first.")
user = os.environ.get("PG_PLACEMENT_USER", "atom_app")
db = "placement_test_db"

eng = create_engine(admin, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :u"), {"u": user}).scalar():
        c.execute(text(f"CREATE ROLE {user} LOGIN PASSWORD '{pw.replace(chr(39), chr(39) * 2)}'"))
    if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": db}).scalar():
        c.execute(text(f"CREATE DATABASE {db} OWNER {user}"))
dbeng = create_engine(admin.rsplit("/", 1)[0] + f"/{db}", isolation_level="AUTOCOMMIT")
ddl = (pathlib.Path(__file__).parent / "seed_placement_db.sql").read_text(encoding="utf-8")
with dbeng.connect() as c:
    c.exec_driver_sql(ddl)
    c.exec_driver_sql(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {user}; GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {user};")
print(f"{db} ready for user {user}")
