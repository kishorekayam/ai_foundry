"""Mode 3 works from the user's real collection: correct endpoints, no generated records, zero rule violations in 'valid' cases."""
import json
import time

import pytest

from app.engine.apisource import match_tables, parse_api_source
from app.engine.exporters import build_export
from app.engine.tc_planner import Planner, finalize
from app.engine.tc_validate import body_problems, run_checks
from app.models import Column, ForeignKey, Schema, Table


def col(n, t="integer", **k):
    return Column(name=n, type=t, **k)


SCHEMA = Schema(
    db_type="postgresql", database="d",
    tables=[
        Table(name="django_celery_beat_crontabschedule", columns=[col("id", primary_key=True), col("minute", "varchar", max_length=240)]),
        Table(name="django_celery_beat_periodictask", columns=[
            col("id", primary_key=True), col("name", "varchar", max_length=200, unique=True), col("task", "varchar", max_length=200), col("enabled", "boolean"),
            col("total_run_count", "integer", check="total_run_count >= 0"), col("description", "text", nullable=True), col("crontab_id", nullable=True),
        ], foreign_keys=[ForeignKey(column="crontab_id", ref_table="django_celery_beat_crontabschedule", ref_column="id")]),
    ],
)

COLLECTION = {
    "info": {"name": "Scheduler API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "item": [
        {"name": "Periodic tasks", "item": [
            {"name": "Create task", "request": {"method": "POST", "header": [{"key": "Authorization", "value": "Bearer secret-token"}, {"key": "Content-Type", "value": "application/json"}],
                "url": {"raw": "{{baseUrl}}/api/v1/periodic-tasks"},
                "body": {"mode": "raw", "raw": json.dumps({"name": "Nightly cleanup", "task": "app.tasks.cleanup", "enabled": True, "totalRunCount": 0, "description": "clean", "crontabId": 1})}},
             "response": [{"code": 201}]},
            {"name": "Get task", "request": {"method": "GET", "header": [], "url": {"raw": "{{baseUrl}}/api/v1/periodic-tasks/:id"}}},
            {"name": "Update task", "request": {"method": "PATCH", "header": [], "url": {"raw": "{{baseUrl}}/api/v1/periodic-tasks/:id"}, "body": {"mode": "raw", "raw": json.dumps({"description": "x"})}}},
            {"name": "Delete task", "request": {"method": "DELETE", "header": [], "url": {"raw": "{{baseUrl}}/api/v1/periodic-tasks/:id"}}},
            {"name": "List tasks", "request": {"method": "GET", "header": [], "url": {"raw": "{{baseUrl}}/api/v1/periodic-tasks"}}},
        ]},
    ],
}
ALL = ["positive", "negative", "boundary", "workflow"]


def plan(samples=None):
    src = parse_api_source(json.dumps(COLLECTION))
    match_tables(src, SCHEMA)
    cases = finalize(Planner(src, SCHEMA, ALL, samples).plan())
    return src, cases


def test_real_endpoints_are_read_and_matched_to_the_table():
    src = parse_api_source(json.dumps(COLLECTION))
    match_tables(src, SCHEMA)
    assert src.kind == "postman" and src.base_url == "{{baseUrl}}"
    assert {e.key for e in src.endpoints} == {"POST /api/v1/periodic-tasks", "GET /api/v1/periodic-tasks/{id}", "PATCH /api/v1/periodic-tasks/{id}", "DELETE /api/v1/periodic-tasks/{id}", "GET /api/v1/periodic-tasks"}
    assert {e.table for e in src.endpoints} == {"django_celery_beat_periodictask"}
    post = next(e for e in src.endpoints if e.method == "POST")
    assert post.headers["Authorization"] == "{{authToken}}" and post.ok_status == "201"  # the token is never kept


def test_cases_use_collection_paths_never_table_names():
    src, cases = plan()
    paths = {c.fixture.path for c in cases if not c.requests} | {r.path for c in cases for r in c.requests or []}
    assert paths and all(p.startswith("/api/v1/periodic-tasks") or p == "{{x}}" for p in paths), paths
    assert not any("django-celery" in p for p in paths)
    assert {c.category for c in cases} == set(ALL)
    assert all(c.prerequisite_records == [] for c in cases)  # nothing is generated or loaded


def test_valid_cases_pass_and_negative_cases_really_break_a_rule():
    src, cases = plan()
    checks = run_checks(SCHEMA, src, cases, ALL, {})
    assert [(c.id, c.status, c.detail) for c in checks if c.status == "failed"] == []
    titles = [c.title for c in cases]
    assert any("missing name" in t for t in titles) and any("over maximum length" in t for t in titles) and any("duplicate name" in t for t in titles)
    assert any("create, delete" in t for t in titles) and any("create, then retrieve" in t for t in titles)
    neg = next(c for c in cases if "missing name" in c.title)
    assert "name" not in neg.fixture.body and body_problems(SCHEMA, neg.table, neg.fixture.body) == ["name is missing"]
    assert body_problems(SCHEMA, "django_celery_beat_periodictask", {"name": "a" * 201, "task": "t", "enabled": True, "total_run_count": 0}) == ["name is longer than 200"]
    assert body_problems(SCHEMA, "django_celery_beat_periodictask", {"name": "ok", "task": "t", "enabled": True, "total_run_count": -1}) == ["total_run_count is outside its allowed range"]


def test_existing_rows_supply_valid_parent_ids_and_duplicate_values():
    samples = {"django_celery_beat_periodictask": [{"id": 7, "name": "Existing task", "task": "x", "enabled": True, "total_run_count": 3, "description": None, "crontab_id": 42}]}
    _, cases = plan(samples)
    valid = next(c for c in cases if c.category == "positive" and c.title.endswith("valid request") and c.fixture.method == "POST")
    assert valid.fixture.body["crontabId"] == 42  # a parent that really exists
    dup = next(c for c in cases if "duplicate name" in c.title)
    assert dup.fixture.body["name"] == "Existing task" and "already exists" in dup.preconditions[0]
    get_one = next(c for c in cases if c.category == "positive" and c.fixture.method == "GET" and "{" not in c.fixture.path.split("periodic-tasks")[-1] and c.fixture.path.endswith("/7"))
    assert get_one.preconditions == ["Uses a record that exists in your database"]
    delete_paths = [c.fixture.path for c in cases if c.fixture.method == "DELETE" and not c.requests]
    assert not any(p.endswith("/7") for p in delete_paths)  # real rows are never targeted by DELETE


def test_exports_are_runnable_postman_and_pytest():
    src, cases = plan()
    from app.models import Report

    rep = Report(job_id="j", db_type="postgresql", database="d", tables_discovered=2, mode="testcase", records_requested=0, records_generated=0, data_type_validity=100, relationship_integrity=100,
                 uniqueness_violations=0, status="completed", duration_ms=1, unsupported_constraints=[], adjustments=[], checks=[], per_table=[])
    raw, name, _ = build_export("postman", SCHEMA, {}, [], rep, cases, None)
    pm = json.loads(raw)
    assert [f["name"] for f in pm["item"]] == ["Positive", "Negative", "Boundary", "Workflow"]
    wf = next(i for i in pm["item"][3]["item"] if "create, delete" in i["name"])
    assert wf["item"][1]["request"]["url"]["raw"] == "{{baseUrl}}/api/v1/periodic-tasks/{{createdId}}"
    assert "createdId" in "".join(wf["item"][0]["event"][0]["script"]["exec"])
    py, _, _ = build_export("pytest", SCHEMA, {}, [], rep, cases, None)
    compile(py.decode(), "generated_tests.py", "exec")  # valid Python
    xl, _, _ = build_export("testcase-xlsx", SCHEMA, {}, [], rep, cases, None)
    assert xl[:2] == b"PK"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for k in ("OPENAI_API_KEY", "MYSQL_HOST", "REGISTRY_DB_URL"):
        monkeypatch.setenv(k, "")
    monkeypatch.setenv("BOOMI_ENABLED", "false")
    monkeypatch.setenv("API_USERNAME", "u")
    monkeypatch.setenv("API_PASSWORD", "p-123")
    get_settings.cache_clear()
    c = TestClient(app)
    c.auth = ("u", "p-123")
    yield c
    get_settings.cache_clear()


def test_api_flow_job_runs_and_reports_without_writing_data(client):
    schema = SCHEMA.model_dump(by_alias=True, mode="json")
    p = client.post("/api/collection/parse", json={"text": json.dumps(COLLECTION), "schema": schema})
    assert p.status_code == 200 and len(p.json()["endpoints"]) == 5 and p.json()["endpoints"][0]["table"] == "django_celery_beat_periodictask"
    assert client.post("/api/collection/parse", json={"text": "not json"}).status_code == 422
    cfg = {"mode": "testcase", "tables": [], "locale": "en_US", "testCase": {"categories": ALL, "collectionText": json.dumps(COLLECTION)}}
    jid = client.post("/api/jobs", json={"schema": schema, "config": cfg}).json()["jobId"]
    for _ in range(100):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            break
        time.sleep(0.2)
    assert j["status"] in {"completed", "partial"}, j.get("error") or j["report"]
    assert j["report"]["recordsGenerated"] == 0 and len(j["testCases"]) > 20
    assert not any(c["status"] == "failed" for c in j["report"]["checks"])
    assert client.get(f"/api/jobs/{jid}/export", params={"format": "postman"}).status_code == 200
    # without a collection the job explains what is needed
    cfg["testCase"].pop("collectionText")
    jid = client.post("/api/jobs", json={"schema": schema, "config": cfg}).json()["jobId"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            break
        time.sleep(0.2)
    assert j["status"] == "failed" and "Postman collection" in j["error"]


def test_row_sampling_is_read_only_and_reports_empty_tables(pg):
    import psycopg

    from app.engine.samples import read_samples
    from app.targets import Target

    with psycopg.connect(pg["uri"], autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS samp (id serial primary key, name text, born date, price numeric(8,2))")
        c.execute("CREATE TABLE IF NOT EXISTS samp_empty (id serial primary key)")
        c.execute("INSERT INTO samp (name, born, price) VALUES ('Asha', '2001-02-03', 9.50), ('Ravi', '1999-12-31', 10)")
    t = Target(id="t", label="t", db_type="postgresql", host=pg["host"], port=pg["port"], database="placement_test_db", load_allowed=False, username="postgres", password="", ssl="disable")
    rows, notes = read_samples(t, ["samp", "samp_empty", "missing_table"])
    assert [r["name"] for r in rows["samp"]] == ["Asha", "Ravi"] and rows["samp"][0]["born"] == "2001-02-03" and rows["samp"][0]["price"] == 9.5
    assert rows["samp_empty"] == [] and any("samp_empty" in n for n in notes) and any("missing_table" in n for n in notes)
    with psycopg.connect(pg["uri"], autocommit=True) as c:
        assert c.execute("select count(*) from samp").fetchone()[0] == 2  # nothing was written
        c.execute("DROP TABLE samp, samp_empty")  # the embedded database is shared with other tests
