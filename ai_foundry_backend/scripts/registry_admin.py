"""Administer the common MySQL registry (approved targets + encrypted credentials).

    python scripts/registry_admin.py genkey               # appends REGISTRY_ENCRYPTION_KEY to .env if missing (never printed)
    python scripts/registry_admin.py init                 # creates the database (if MYSQL_ADMIN_URL is set) and the tables
    python scripts/registry_admin.py add-target --id pg-placement-test --label "Placement test DB" --type postgresql \\
        --host localhost --port 5432 --database placement_test_db --username atom_app --password-env PG_PLACEMENT_PASSWORD --load-allowed
    python scripts/registry_admin.py list
    python scripts/registry_admin.py deactivate --id pg-placement-test

Passwords are read from an environment variable or an interactive prompt, never from the command line.
"""
import argparse
import getpass
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402  (loads .env)


def cmd_genkey(_: argparse.Namespace) -> None:
    from cryptography.fernet import Fernet

    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if any(l.startswith("REGISTRY_ENCRYPTION_KEY=") and l.split("=", 1)[1].strip() for l in text.splitlines()):
        print("REGISTRY_ENCRYPTION_KEY already present in .env (left unchanged).")
        return
    lines = [l for l in text.splitlines() if not l.startswith("REGISTRY_ENCRYPTION_KEY=")]
    lines.append(f"REGISTRY_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Generated REGISTRY_ENCRYPTION_KEY and saved it to .env. Back it up: without it stored credentials cannot be decrypted.")


def cmd_init(_: argparse.Namespace) -> None:
    from sqlalchemy import create_engine, text

    from app import registry

    admin = os.environ.get("MYSQL_ADMIN_URL")
    s = get_settings()
    if admin and s.registry_url:
        db = s.registry_url.rsplit("/", 1)[1].split("?")[0]
        with create_engine(admin, isolation_level="AUTOCOMMIT").connect() as c:
            c.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4"))
    if not s.registry_url:
        sys.exit("Registry is not configured. Set MYSQL_HOST/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DATABASE (or REGISTRY_DB_URL) in .env")
    registry.init_schema()
    print("Registry tables ready:", ", ".join(registry.metadata.tables))


def cmd_add(a: argparse.Namespace) -> None:
    from app import registry

    pw = os.environ.get(a.password_env, "") if a.password_env else (getpass.getpass("Target DB password (hidden): ") if a.prompt_password else "")
    uri = os.environ.get(a.uri_env, "") if a.uri_env else ""
    registry.upsert_target(a.id, a.label, a.type, a.host, a.port, a.database, a.username, pw, uri, a.ssl, a.load_allowed)
    print(f"Registered target {a.id} (credentials encrypted).")


def cmd_list(_: argparse.Namespace) -> None:
    from app import registry

    for r in registry.list_rows(active_only=False):
        print(f"{r['id']:24} {r['db_type']:11} {r['host']}:{r['port']}/{r['database_name']}  load={'yes' if r['load_allowed'] else 'no'}  active={'yes' if r['active'] else 'no'}")


def cmd_deactivate(a: argparse.Namespace) -> None:
    from app import registry

    registry.deactivate(a.id)
    print(f"Deactivated {a.id}")


p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = p.add_subparsers(dest="cmd", required=True)
sub.add_parser("genkey").set_defaults(fn=cmd_genkey)
sub.add_parser("init").set_defaults(fn=cmd_init)
sub.add_parser("list").set_defaults(fn=cmd_list)
d = sub.add_parser("deactivate")
d.add_argument("--id", required=True)
d.set_defaults(fn=cmd_deactivate)
a = sub.add_parser("add-target")
a.add_argument("--id", required=True)
a.add_argument("--label", required=True)
a.add_argument("--type", required=True, choices=["postgresql", "mysql", "mongodb"])
a.add_argument("--host", required=True)
a.add_argument("--port", type=int, required=True)
a.add_argument("--database", required=True)
a.add_argument("--username", default="")
a.add_argument("--password-env", default="")
a.add_argument("--prompt-password", action="store_true")
a.add_argument("--uri-env", default="")
a.add_argument("--ssl", default="prefer")
a.add_argument("--load-allowed", action="store_true")
a.set_defaults(fn=cmd_add)
args = p.parse_args()
args.fn(args)
