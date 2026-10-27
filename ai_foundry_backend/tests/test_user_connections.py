import pytest
from cryptography.fernet import Fernet

H1 = {"X-Client-Id": "browser_one_12345"}
H2 = {"X-Client-Id": "browser_two_67890"}


@pytest.fixture
def api(pg, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import registry
    from app.config import get_settings
    from app.main import app

    monkeypatch.setenv("REGISTRY_DB_URL", f"sqlite:///{tmp_path / 'reg.db'}")
    monkeypatch.setenv("REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "true")  # the embedded test database is on 127.0.0.1
    monkeypatch.setenv("BOOMI_ENABLED", "false")  # tests must not depend on the developer's .env
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("API_USERNAME", "api_user")
    monkeypatch.setenv("API_PASSWORD", "api_pass-123")
    get_settings.cache_clear()
    registry.reset_cache()
    registry.init_schema()
    c = TestClient(app)
    c.auth = ("api_user", "api_pass-123")
    yield c
    registry.reset_cache()
    monkeypatch.undo()
    get_settings.cache_clear()


def body(pg, **kw):
    b = {"dbType": "postgresql", "host": pg["host"], "port": pg["port"], "database": "placement_test_db", "username": "postgres", "password": "", "ssl": "disable", "label": "My test DB", "allowLoad": True}
    return {**b, **kw}


def test_user_enters_own_connection_and_it_is_saved_encrypted(api, pg):
    r = api.post("/api/connections/test", json=body(pg), headers=H1).json()
    assert r["ok"], r["message"]
    assert r["tablesDiscovered"] == 8 and r["targetId"].startswith("t_")
    saved = api.get("/api/targets", headers=H1).json()
    assert [t["label"] for t in saved] == ["My test DB"] and saved[0]["loadAllowed"] is True
    assert "password" not in str(saved).lower()
    assert api.get("/api/targets", headers=H2).json() == []  # other browsers cannot see it
    assert api.post("/api/schema", json={"targetId": r["targetId"]}, headers=H2).status_code == 404
    assert len(api.post("/api/schema", json={"targetId": r["targetId"]}, headers=H1).json()["tables"]) == 8
    again = api.post("/api/connections/test", json=body(pg), headers=H1).json()
    assert again["targetId"] == r["targetId"]  # same connection is reused, not duplicated
    # re-test via saved connection id needs no credentials
    assert api.post("/api/connections/test", json={"dbType": "postgresql", "targetId": r["targetId"]}, headers=H1).json()["ok"]


def test_policy_and_errors(api, pg, monkeypatch):
    assert api.post("/api/connections/test", json=body(pg), headers={}).status_code == 400  # client id required
    meta = api.post("/api/connections/test", json=body(pg, host="169.254.169.254", port=80), headers=H1).json()
    assert not meta["ok"] and "network policy" in meta["message"]
    bad_pw = api.post("/api/connections/test", json=body(pg, database="nope"), headers=H1).json()
    assert not bad_pw["ok"] and "postgres" not in bad_pw["message"].lower()
    assert api.get("/api/targets", headers=H1).json() == []  # failed attempts are not saved
    from app.config import get_settings

    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "false")
    get_settings.cache_clear()
    priv = api.post("/api/connections/test", json=body(pg), headers=H1).json()
    assert not priv["ok"] and "Private" in priv["message"]


def test_internal_metadata_for_boomi_uses_registry_credentials(api, pg):
    tid = api.post("/api/connections/test", json=body(pg), headers=H1).json()["targetId"]
    assert api.post("/internal/metadata", json={"targetId": tid}, auth=None).status_code == 401
    r = api.post("/internal/metadata", json={"targetId": tid})
    assert r.status_code == 200 and len(r.json()["tables"]) == 8
    assert api.delete(f"/api/targets/{tid}", headers=H2).status_code == 404
    assert api.delete(f"/api/targets/{tid}", headers=H1).status_code == 200
    assert api.post("/internal/metadata", json={"targetId": tid}).status_code == 404


def test_boomi_gate_and_audit_endpoints(api, pg):
    from app import registry

    tid = api.post("/api/connections/test", json=body(pg), headers=H1).json()["targetId"]
    ok = api.post("/internal/registry/lookup", json={"targetId": tid}).json()
    assert ok == {"found": 1, "db_type": "postgresql", "load_allowed": 1}
    assert api.post("/internal/registry/lookup", json={"targetId": "nope"}).json() == {"found": 0, "db_type": "", "load_allowed": 0}
    assert api.post("/internal/registry/lookup", json={"targetId": tid}, auth=None).status_code == 401
    r = api.post("/internal/audit", json={"requestId": "r9", "processName": "A-metadata", "status": "COMPLETE", "targetId": tid}).json()
    assert r == {"recorded": True}
    assert [(x["source"], x["status"]) for x in registry.recent_audit("r9")] == [("boomi", "COMPLETE")]


def test_basic_auth_protects_every_api(api, pg):
    bad = ("api_user", "wrong")
    for method, path in [("get", "/api/targets"), ("get", "/api/auth/check"), ("post", "/api/schema"), ("get", "/api/jobs/job_x"), ("post", "/internal/metadata"), ("post", "/internal/audit")]:
        assert getattr(api, method)(path, headers=H1, auth=None).status_code == 401, path          # no credentials
        assert getattr(api, method)(path, headers=H1, auth=bad).status_code == 401, path             # wrong password
    assert api.get("/api/auth/check", headers=H1).json() == {"ok": True}
    assert api.get("/api/auth/check", headers=H1, auth=("api_user", "wrong")).headers.get("www-authenticate") is None  # no browser popup for /api
    assert "Basic" in api.post("/internal/metadata", json={"targetId": "x"}, auth=None).headers["www-authenticate"]
    assert api.get("/health", auth=None).status_code == 200  # status only, no data


def test_fails_closed_without_configured_credentials(api, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("API_PASSWORD", "")
    get_settings.cache_clear()
    assert api.get("/api/targets", headers=H1).status_code == 503


def test_postgres_schema_selection_discovery_and_load(api, pg):
    import psycopg

    with psycopg.connect(pg["uri"], autocommit=True) as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS alt")
        c.execute("CREATE TABLE IF NOT EXISTS alt.depts (dept_id SERIAL PRIMARY KEY, name VARCHAR(50) NOT NULL UNIQUE)")
        c.execute("CREATE TABLE IF NOT EXISTS alt.staff (staff_id SERIAL PRIMARY KEY, dept_id INTEGER NOT NULL REFERENCES alt.depts(dept_id), univ_id INTEGER REFERENCES public.universities(university_id))")

    # default schema is public: the alt tables are not visible
    pub = api.post("/api/connections/test", json=body(pg), headers=H1).json()
    assert pub["ok"] and pub["tablesDiscovered"] == 8

    r = api.post("/api/connections/test", json=body(pg, schema="alt", label="Alt schema"), headers=H1).json()
    assert r["ok"] and r["tablesDiscovered"] == 2 and r["targetId"] != pub["targetId"]  # same DB, different schema = separate saved connection
    saved = {t["label"]: t for t in api.get("/api/targets", headers=H1).json()}
    assert saved["Alt schema"]["schemaName"] == "alt"
    sch = api.post("/api/schema", json={"targetId": r["targetId"]}, headers=H1).json()
    assert sch["schemaName"] == "alt" and {t["name"] for t in sch["tables"]} == {"depts", "staff"}
    assert any("outside schema" in w for w in sch["warnings"])  # the FK to public.universities is reported, not silently modelled
    staff = next(t for t in sch["tables"] if t["name"] == "staff")
    assert [f["refTable"] for f in staff["foreignKeys"]] == ["depts"]

    jid = api.post("/api/jobs", json={"schema": sch, "config": {"mode": "fast", "locale": "en_US", "seed": 1, "tables": [{"table": "depts", "count": 6}]}}, headers=H1).json()["jobId"]
    import time
    while (j := api.get(f"/api/jobs/{jid}").json())["status"] == "running":
        time.sleep(0.2)
    assert j["status"] == "completed"
    lid = api.post(f"/api/jobs/{jid}/load", json={"targetId": r["targetId"], "approved": True}, headers=H1).json()["loadId"]
    for _ in range(100):
        l = api.get(f"/api/loads/{lid}").json()
        if l["status"] != "running":
            break
        time.sleep(0.2)
    assert l["status"] == "success", l
    with psycopg.connect(pg["uri"]) as c:
        assert c.execute("select count(*) from alt.depts").fetchone()[0] == 6
        c.execute("insert into alt.depts(name) values ('Sequence ok')")  # sequence in the alt schema was advanced
    sql = api.get(f"/api/jobs/{jid}/export", params={"format": "sql-postgres"}, headers=H1).text
    assert 'INSERT INTO "alt"."depts"' in sql

    assert api.post("/api/connections/test", json=body(pg, schema="bad schema;drop"), headers=H1).json()["ok"] is False


DJANGO_LIKE_DDL = """
CREATE SCHEMA IF NOT EXISTS dj;
CREATE TABLE dj.auth_group (id SERIAL PRIMARY KEY, name VARCHAR(150) NOT NULL UNIQUE);
CREATE TABLE dj.django_content_type (id SERIAL PRIMARY KEY, app_label VARCHAR(100) NOT NULL, model VARCHAR(100) NOT NULL, UNIQUE (app_label, model));
CREATE TABLE dj.auth_permission (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, content_type_id INTEGER NOT NULL REFERENCES dj.django_content_type(id), codename VARCHAR(100) NOT NULL, UNIQUE (content_type_id, codename));
CREATE TABLE dj.auth_group_permissions (id BIGSERIAL PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES dj.auth_group(id), permission_id INTEGER NOT NULL REFERENCES dj.auth_permission(id), UNIQUE (group_id, permission_id));
CREATE TABLE dj.tenants_client (id SERIAL PRIMARY KEY, schema_name VARCHAR(63) NOT NULL UNIQUE, name VARCHAR(100) NOT NULL, paid_until DATE NOT NULL, on_trial BOOLEAN NOT NULL, created_on DATE NOT NULL);
CREATE TABLE dj.tenant_branding (id SERIAL PRIMARY KEY, tenant_id INTEGER NOT NULL UNIQUE REFERENCES dj.tenants_client(id), is_active BOOLEAN NOT NULL, primary_color_hex VARCHAR(7) NOT NULL, settings JSONB NOT NULL, uid UUID NOT NULL UNIQUE, rank_no INTEGER NOT NULL UNIQUE, budget NUMERIC(6,2) NOT NULL, tags TEXT[] NOT NULL, ip INET, opens_at TIME, retention INTERVAL, blob BYTEA, updated TIMESTAMPTZ NOT NULL, ratio DOUBLE PRECISION NOT NULL, small SMALLINT NOT NULL CHECK (small >= 0));
CREATE TABLE dj.tenants_domain (id SERIAL PRIMARY KEY, domain VARCHAR(253) NOT NULL UNIQUE, tenant_id INTEGER NOT NULL REFERENCES dj.tenants_client(id), is_primary BOOLEAN NOT NULL);
CREATE TABLE dj.django_session (session_key VARCHAR(40) PRIMARY KEY, session_data TEXT NOT NULL, expire_date TIMESTAMPTZ NOT NULL);
"""


def test_django_like_schema_every_check_passes_and_loads(api, pg):
    import time

    import psycopg

    with psycopg.connect(pg["uri"], autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS dj CASCADE")
        c.execute(DJANGO_LIKE_DDL)
    cx = api.post("/api/connections/test", json=body(pg, schema="dj", label="Django-like"), headers=H1).json()
    assert cx["ok"] and cx["tablesDiscovered"] == 8, cx
    sch = api.post("/api/schema", json={"targetId": cx["targetId"]}, headers=H1).json()
    by = {t["name"]: t for t in sch["tables"]}
    assert sorted(map(sorted, by["django_content_type"]["uniqueTogether"])) == [["app_label", "model"]]
    br = {c["name"]: c for c in by["tenant_branding"]["columns"]}
    assert br["budget"]["precision"] == 6 and br["budget"]["scale"] == 2 and br["settings"]["type"] == "json" and br["tags"]["type"] == "array:text" and br["ip"]["type"] == "inet" and br["retention"]["type"] == "interval"

    counts = {"auth_group": 12, "django_content_type": 15, "auth_permission": 60, "auth_group_permissions": 100, "tenants_client": 40, "tenant_branding": 60, "tenants_domain": 80, "django_session": 30}
    cfg = {"mode": "fast", "locale": "en_IN", "tables": [{"table": k, "count": v} for k, v in counts.items()]}

    def run(config):
        jid = api.post("/api/jobs", json={"schema": sch, "config": config}, headers=H1).json()["jobId"]
        while (j := api.get(f"/api/jobs/{jid}").json())["status"] == "running":
            time.sleep(0.2)
        return jid, j

    jid, j = run(cfg)
    failed = [(c["label"], c["detail"]) for c in j["report"]["checks"] if c["status"] == "failed"]
    assert not failed, failed
    assert j["report"]["uniquenessViolations"] == 0 and j["report"]["dataTypeValidity"] == 100
    rows = {t: api.get(f"/api/jobs/{jid}/preview", params={"table": t, "page_size": 100}, headers=H1).json() for t in ("tenant_branding", "auth_group_permissions")}
    assert rows["tenant_branding"]["total"] == 40  # unique FK to 40 tenants caps the count (reported as an adjustment)
    assert any("tenant_branding" in a for a in j["report"]["adjustments"])
    assert all(abs(r["budget"]) < 10000 for r in rows["tenant_branding"]["rows"])  # numeric(6,2) never overflows
    pairs = {(r["group_id"], r["permission_id"]) for r in rows["auth_group_permissions"]["rows"]}
    assert len(pairs) == rows["auth_group_permissions"]["total"]  # composite unique pair really is unique

    # scenario mode with a BOOLEAN scenario written as text
    scen = {**cfg, "mode": "scenario", "description": "Multi tenant admin console. Generate 7 TRUE is_active tenant brandings", "scenarios": [{"table": "tenant_branding", "column": "is_active", "value": "TRUE", "count": 7}]}
    sid, sj = run(scen)
    assert not [c for c in sj["report"]["checks"] if c["status"] == "failed"], sj["report"]["checks"]
    assert sj["report"]["scenarioCoverage"][0]["generated"] == 7 and sj["report"]["scenarioCoverage"][0]["result"] == "Covered"

    # the data really loads into PostgreSQL (uuid / jsonb / array / inet / interval / bytea / timestamptz)
    lid = api.post(f"/api/jobs/{jid}/load", json={"targetId": cx["targetId"], "approved": True}, headers=H1).json()["loadId"]
    for _ in range(200):
        l = api.get(f"/api/loads/{lid}").json()
        if l["status"] != "running":
            break
        time.sleep(0.2)
    assert l["status"] == "success", (l["error"], [p for p in l["perTable"] if p["failedBatches"]])
    with psycopg.connect(pg["uri"]) as c:
        assert c.execute("select count(*) from dj.tenant_branding").fetchone()[0] == 40
        assert c.execute("select count(distinct (group_id, permission_id)) from dj.auth_group_permissions").fetchone()[0] == c.execute("select count(*) from dj.auth_group_permissions").fetchone()[0]
    for fmt in ("xlsx", "csv-zip", "json", "sql-postgres"):
        assert api.get(f"/api/jobs/{jid}/export", params={"format": fmt}, headers=H1).status_code == 200, fmt


SHOP_DDL = """
DROP SCHEMA IF EXISTS shop CASCADE;
CREATE SCHEMA shop;
CREATE TYPE shop.cust_status AS ENUM ('active', 'blocked', 'pending');
CREATE TABLE shop.categories (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, parent_id INTEGER REFERENCES shop.categories(id), name VARCHAR(80) NOT NULL UNIQUE, slug VARCHAR(80) NOT NULL UNIQUE);
CREATE TABLE shop.customers (id BIGSERIAL PRIMARY KEY, email VARCHAR(120) NOT NULL UNIQUE, first_name VARCHAR(40) NOT NULL, last_name VARCHAR(40) NOT NULL, country CHAR(2) NOT NULL, birth_date DATE NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, loyalty_points INTEGER NOT NULL DEFAULT 0 CHECK (loyalty_points >= 0), status shop.cust_status NOT NULL);
CREATE TABLE shop.profiles (customer_id BIGINT PRIMARY KEY REFERENCES shop.customers(id), bio TEXT, website VARCHAR(200), avatar BYTEA);
CREATE TABLE shop.products (id SERIAL PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES shop.categories(id), sku VARCHAR(20) NOT NULL UNIQUE, title VARCHAR(200) NOT NULL, price NUMERIC(12,4) NOT NULL CHECK (price >= 0.01), price_with_tax NUMERIC(14,4) GENERATED ALWAYS AS (price * 1.18) STORED, stock INTEGER NOT NULL CHECK (stock BETWEEN 0 AND 5000), weight_kg DOUBLE PRECISION, tags TEXT[], attrs JSONB);
CREATE TABLE shop.orders (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), customer_id BIGINT NOT NULL REFERENCES shop.customers(id), placed_at TIMESTAMPTZ NOT NULL, shipped_at TIMESTAMPTZ, status VARCHAR(20) NOT NULL CHECK (status IN ('NEW','PAID','SHIPPED','CANCELLED')), total NUMERIC(12,2) NOT NULL);
CREATE TABLE shop.order_items (order_id UUID NOT NULL REFERENCES shop.orders(id), product_id INTEGER NOT NULL REFERENCES shop.products(id), qty SMALLINT NOT NULL CHECK (qty > 0), PRIMARY KEY (order_id, product_id));
CREATE TABLE shop.wishlist (customer_id BIGINT NOT NULL REFERENCES shop.customers(id), product_id INTEGER NOT NULL REFERENCES shop.products(id), UNIQUE (customer_id, product_id));
"""


def test_completely_different_schema_works_from_metadata_alone(api, pg):
    """No schema-specific code: composite PK, identity-always, generated column, enum type, self FK, PK that is an FK, no-PK table."""
    import time

    import psycopg

    with psycopg.connect(pg["uri"], autocommit=True) as c:
        c.execute(SHOP_DDL)
    cx = api.post("/api/connections/test", json=body(pg, schema="shop", label="Shop"), headers=H1).json()
    assert cx["ok"] and cx["tablesDiscovered"] == 7, cx
    sch = api.post("/api/schema", json={"targetId": cx["targetId"]}, headers=H1).json()
    by = {t["name"]: t for t in sch["tables"]}
    assert by["order_items"]["uniqueTogether"] == [["order_id", "product_id"]]  # composite PK became a combination key
    assert not any(c["primaryKey"] for c in by["order_items"]["columns"])
    assert next(c for c in by["products"]["columns"] if c["name"] == "price_with_tax")["generated"] is True
    assert next(c for c in by["categories"]["columns"] if c["name"] == "id")["identityAlways"] is True
    assert next(c for c in by["customers"]["columns"] if c["name"] == "status")["enumValues"] == ["active", "blocked", "pending"]
    assert next(c for c in by["products"]["columns"] if c["name"] == "price")["check"]

    counts = {"categories": 12, "customers": 40, "profiles": 25, "products": 50, "orders": 60, "order_items": 120, "wishlist": 70}
    cfg = {"mode": "fast", "locale": "en_US", "tables": [{"table": k, "count": v} for k, v in counts.items()]}
    jid = api.post("/api/jobs", json={"schema": sch, "config": cfg}, headers=H1).json()["jobId"]
    while (j := api.get(f"/api/jobs/{jid}").json())["status"] == "running":
        time.sleep(0.2)
    failed = [(c["label"], c["detail"]) for c in j["report"]["checks"] if c["status"] == "failed"]
    assert not failed, failed
    assert j["report"]["uniquenessViolations"] == 0 and j["report"]["relationshipIntegrity"] == 100

    lid = api.post(f"/api/jobs/{jid}/load", json={"targetId": cx["targetId"], "approved": True}, headers=H1).json()["loadId"]
    for _ in range(300):
        l = api.get(f"/api/loads/{lid}").json()
        if l["status"] != "running":
            break
        time.sleep(0.2)
    assert l["status"] == "success", (l["error"], l["verification"], [p for p in l["perTable"] if p["inserted"] != p["expected"]])
    with psycopg.connect(pg["uri"]) as c:
        assert c.execute("select count(*) from shop.order_items").fetchone()[0] == j["report"]["perTable"][[p["table"] for p in j["report"]["perTable"]].index("order_items")]["generated"]
        assert c.execute("select count(*) from shop.products where price_with_tax is not null").fetchone()[0] == 50  # the database computed the generated column
        assert c.execute("select count(*) from shop.customers where updated_at < created_at").fetchone()[0] == 0  # date ordering from column names
        c.execute("insert into shop.categories(name, slug) values ('seq-ok', 'seq-ok')")  # identity sequence advanced past the loaded keys


def test_load_into_a_database_that_already_has_data(api, pg):
    """Real databases are not empty: keys must not clash with existing rows, and rows that clash on a unique value are
    skipped (with their dependants) and reported instead of failing the whole load."""
    import time

    import psycopg

    with psycopg.connect(pg["uri"], autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS ne CASCADE")
        c.execute("CREATE SCHEMA ne")
        c.execute("CREATE TABLE ne.parent (id SERIAL PRIMARY KEY, code VARCHAR(30) NOT NULL UNIQUE)")
        c.execute("CREATE TABLE ne.child (id SERIAL PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES ne.parent(id), label VARCHAR(20) NOT NULL)")
        c.execute("INSERT INTO ne.parent(code) SELECT 'pre' || g FROM generate_series(1, 5) g")  # ids 1..5 already used
        c.execute("INSERT INTO ne.child(parent_id, label) VALUES (1, 'old')")
    cx = api.post("/api/connections/test", json=body(pg, schema="ne", label="Non-empty"), headers=H1).json()
    assert cx["ok"], cx
    sch = api.post("/api/schema", json={"targetId": cx["targetId"]}, headers=H1).json()
    cfg = {"mode": "fast", "locale": "en_US", "seed": 3, "tables": [{"table": "parent", "count": 10}, {"table": "child", "count": 30}]}
    jid = api.post("/api/jobs", json={"schema": sch, "config": cfg}, headers=H1).json()["jobId"]
    while (j := api.get(f"/api/jobs/{jid}").json())["status"] == "running":
        time.sleep(0.2)
    assert j["status"] == "completed"
    parents = api.get(f"/api/jobs/{jid}/preview", params={"table": "parent", "page_size": 100}, headers=H1).json()["rows"]
    children = api.get(f"/api/jobs/{jid}/preview", params={"table": "child", "page_size": 100}, headers=H1).json()["rows"]
    clash = parents[:2]
    with psycopg.connect(pg["uri"], autocommit=True) as c:  # two of the generated codes already exist in the database
        for p in clash:
            c.execute("INSERT INTO ne.parent(code) VALUES (%s)", (p["code"],))
    doomed = [ch for ch in children if ch["parent_id"] in {p["id"] for p in clash}]

    lid = api.post(f"/api/jobs/{jid}/load", json={"targetId": cx["targetId"], "approved": True}, headers=H1).json()["loadId"]
    for _ in range(200):
        l = api.get(f"/api/loads/{lid}").json()
        if l["status"] != "running":
            break
        time.sleep(0.2)
    assert l["status"] == "success", (l["error"], l["verification"], l["perTable"])
    per = {p["table"]: p for p in l["perTable"]}
    assert per["parent"]["skipped"] == 2 and per["parent"]["inserted"] == 8
    assert per["child"]["skipped"] == len(doomed) and per["child"]["inserted"] == 30 - len(doomed)
    assert l["warnings"] and l["verification"] == {"countsMatch": True, "fkValid": True}
    with psycopg.connect(pg["uri"]) as c:
        assert c.execute("select count(*) from ne.parent").fetchone()[0] == 5 + 2 + 8
        assert c.execute("select count(*) from ne.child").fetchone()[0] == 1 + 30 - len(doomed)
        assert c.execute("select count(*) from ne.child ch left join ne.parent p on p.id = ch.parent_id where p.id is null").fetchone()[0] == 0
        assert c.execute("select min(id) from ne.parent where code not like 'pre%%' and code not in (%s, %s)", tuple(p["code"] for p in clash)).fetchone()[0] > 7  # new keys come after the existing ones
