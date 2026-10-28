# tests/test_e2e.py
import json
import time

import psycopg

ALL_TABLES = ["universities", "departments", "students", "placement_providers", "supervisors", "placements", "timesheets", "timesheet_reviews"]


def wait_job(client, job_id):
    for _ in range(200):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def get_schema(client):
    r = client.post("/api/schema", json={"targetId": "pg-placement-test"})
    assert r.status_code == 200, r.text
    return r.json()


def counts(n_ts=40):
    return [{"table": t, "count": n_ts if t == "timesheets" else (0 if t == "timesheet_reviews" else 20)} for t in ALL_TABLES]


def test_targets_and_connection(client):
    assert client.get("/api/targets").json()[0]["id"] == "pg-placement-test"
    r = client.post("/api/connections/test", json={"dbType": "postgresql", "targetId": "pg-placement-test"}).json()
    assert r["ok"] and r["tablesDiscovered"] == 8 and r["metadataAccess"] == "Allowed"
    bad = client.post("/api/connections/test", json={"dbType": "postgresql", "host": "evil.example.com", "port": 5432, "database": "x", "username": "a", "password": "b"}).json()
    assert not bad["ok"] and "approved" in bad["message"]


def test_schema_extraction_matches_ddl(client):
    s = get_schema(client)
    t = {x["name"]: x for x in s["tables"]}
    assert len(t) == 8
    ts = {c["name"]: c for c in t["timesheets"]["columns"]}
    assert sorted(ts["status"]["enumValues"]) == sorted(["SUBMITTED", "PENDING", "APPROVED", "REJECTED", "QUERIED"])
    assert ts["hours_worked"]["check"] and ts["timesheet_id"]["primaryKey"] and ts["timesheet_id"]["maxLength"] == 12
    assert {f["refTable"] for f in t["timesheets"]["foreignKeys"]} == {"placements", "students"}
    assert next(c for c in t["universities"]["columns"] if c["name"] == "university_id")["type"] == "serial"
    assert next(c for c in t["students"]["columns"] if c["name"] == "email")["unique"]
    assert next(c for c in t["students"]["columns"] if c["name"] == "phone")["nullable"]
    assert ts["submitted_at"]["type"] == "timestamp"


def test_fast_scenario_testcase_export_load(client, pg):
    schema = get_schema(client)

    # Fast Test
    jid = client.post("/api/jobs", json={"schema": schema, "config": {"mode": "fast", "locale": "en_IN", "seed": 7, "tables": counts(60)}}).json()["jobId"]
    j = wait_job(client, jid)
    assert j["status"] == "completed", j["report"]
    assert j["report"]["relationshipIntegrity"] == 100 and j["report"]["uniquenessViolations"] == 0
    pv = client.get(f"/api/jobs/{jid}/preview", params={"table": "timesheets", "page": 0, "page_size": 20}).json()
    assert pv["total"] == 60 and len(pv["rows"]) == 20

    # Scenario with missing coverage, then Generate Missing
    desc = "An Indian university placement app. Generate 30 approved timesheets, 10 pending timesheets, 5 rejected timesheets and 5 queried timesheets"
    sid = client.post("/api/jobs", json={"schema": schema, "config": {"mode": "scenario", "locale": "en_IN", "tables": counts(40), "description": desc}}).json()["jobId"]
    sj = wait_job(client, sid)
    cov = {c["scenario"]["value"]: c for c in sj["report"]["scenarioCoverage"]}
    assert cov["APPROVED"]["result"] == "Covered" and cov["REJECTED"]["result"] == "Missing"
    sj = client.post(f"/api/jobs/{sid}/generate-missing").json()
    assert all(c["result"] == "Covered" for c in sj["report"]["scenarioCoverage"]), sj["report"]["scenarioCoverage"]

    # Test case generator: written against a real collection, no records generated
    collection = {"info": {"name": "Placement API"}, "item": [
        {"name": "Create timesheet", "request": {"method": "POST", "header": [], "url": {"raw": "{{baseUrl}}/api/timesheets"}, "body": {"mode": "raw", "raw": '{"placementId": 1, "weekStart": "2025-01-06", "hoursWorked": 20, "status": "PENDING"}'}}},
        {"name": "Get timesheet", "request": {"method": "GET", "header": [], "url": {"raw": "{{baseUrl}}/api/timesheets/:id"}}},
    ]}
    body = {"schema": schema, "config": {"mode": "testcase", "locale": "en_IN", "tables": [], "testCase": {"categories": ["positive", "negative", "boundary", "workflow"], "collectionText": json.dumps(collection)}}}
    tid = client.post("/api/jobs", json=body).json()["jobId"]
    tj = wait_job(client, tid)
    assert tj["status"] in {"completed", "partial"}, tj["report"]["checks"]
    assert not any(c["status"] == "failed" for c in tj["report"]["checks"]) and tj["report"]["recordsGenerated"] == 0
    assert {c["fixture"]["path"] for c in tj["testCases"] if not c.get("requests")} <= {"/api/timesheets", "/api/timesheets/{id}", "/api/timesheets/987654321", "/api/timesheets/not-an-id"}

    # Exports
    for fmt in ["xlsx", "csv-zip", "json", "sql-postgres", "report-json", "report-xlsx"]:
        r = client.get(f"/api/jobs/{jid}/export", params={"format": fmt})
        assert r.status_code == 200 and len(r.content) > 200, fmt
    for fmt in ["testcase-xlsx", "pytest", "mapping-report", "postman"]:
        assert client.get(f"/api/jobs/{tid}/export", params={"format": fmt}).status_code == 200

    # Approved load into the real (embedded) PostgreSQL, then verify directly
    assert client.post(f"/api/jobs/{jid}/load", json={"targetId": "pg-placement-test", "approved": False}).status_code == 400
    plan = client.post(f"/api/jobs/{jid}/load-plan", json={"targetId": "pg-placement-test"}).json()
    assert plan["tables"][0]["table"] in ("universities", "placement_providers")
    lid = client.post(f"/api/jobs/{jid}/load", json={"targetId": "pg-placement-test", "approved": True}).json()["loadId"]
    for _ in range(100):
        l = client.get(f"/api/loads/{lid}").json()
        if l["status"] != "running":
            break
        time.sleep(0.2)
    assert l["status"] == "success", (l["error"], l["verification"], [p for p in l["perTable"] if p["inserted"] != p["expected"]])
    assert l["verification"] == {"countsMatch": True, "fkValid": True}
    with psycopg.connect(pg["uri"], autocommit=True) as c:
        assert c.execute("select count(*) from timesheets").fetchone()[0] == 60
        assert c.execute("select count(*) from students s left join universities u on u.university_id=s.university_id where u.university_id is null").fetchone()[0] == 0
        c.execute("insert into universities(name,city,country,established_year,contact_email) values ('Seq Test U','x','y',1900,'a@b.c')")  # sequence was advanced
