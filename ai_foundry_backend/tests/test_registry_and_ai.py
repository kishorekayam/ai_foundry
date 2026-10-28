# tests/test_registry_and_ai.py
import json

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def reg(monkeypatch, tmp_path):
    from app import registry
    from app.config import get_settings

    monkeypatch.setenv("REGISTRY_DB_URL", f"sqlite:///{tmp_path / 'reg.db'}")
    monkeypatch.setenv("REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    registry.reset_cache()
    registry.init_schema()
    yield registry
    registry.reset_cache()
    monkeypatch.undo()
    get_settings.cache_clear()


def test_registry_encrypts_credentials_and_targets_read_them(reg):
    from app.targets import get_target, load_targets, match_target

    reg.upsert_target("pg-x", "PG X", "postgresql", "db.internal", 5432, "app_db", "appuser", "s3cret-pw", ssl_mode="require", load_allowed=True)
    raw = reg.list_rows()[0]
    assert "s3cret-pw" not in json.dumps(raw, default=str) and raw["password_enc"]
    t = get_target("pg-x")
    assert t and t.password == "s3cret-pw" and t.username == "appuser" and t.load_allowed
    assert "s3cret-pw" not in t.public().model_dump_json()
    assert match_target("postgresql", "db.internal", 5432, "app_db").id == "pg-x"
    assert match_target("postgresql", "evil.example.com", 5432, "app_db") is None
    reg.deactivate("pg-x")
    assert "pg-x" not in load_targets()


def test_registry_audit_trail(reg):
    reg.audit("req1", "metadata", "REQUESTED", "x", "pg-x")
    reg.audit("req1", "metadata", "COMPLETE", "", "pg-x")
    assert [r["status"] for r in reg.recent_audit("req1")] == ["REQUESTED", "COMPLETE"]


def test_openai_blueprint_is_validated_against_schema(monkeypatch):
    from app import ai
    from app.config import get_settings
    from app.models import JobConfig, Schema, Column, Table

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    schema = Schema(db_type="postgresql", database="d", tables=[Table(name="orders", columns=[
        Column(name="order_id", type="serial", primary_key=True),
        Column(name="status", type="varchar", enum_values=["PLACED", "REFUNDED"]),
        Column(name="note", type="varchar", max_length=10, nullable=True),
    ])])
    captured = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "domain": "Indian grocery delivery", "localeHint": "en_IN",
                "scenarios": [{"table": "orders", "column": "status", "value": "refunded", "count": 20}, {"table": "ghost", "column": "x", "value": "Y", "count": 1}],
                "valuePools": [{"table": "orders", "column": "status", "values": ["BAD"]}, {"table": "orders", "column": "note", "values": ["Leave at door and ring bell twice"]}],
                "columnRules": [], "notes": ["ok"]})}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, body=json, auth=headers["Authorization"])
        return R()

    monkeypatch.setattr(ai.httpx, "post", fake_post)
    bp, src = ai.plan_blueprint(schema, JobConfig(mode="scenario", locale="en_US", description="Indian grocery delivery app with 20 refunded orders", tables=[]))
    assert src == "ai" and captured["url"].endswith("/chat/completions") and captured["body"]["model"] == "gpt-4o"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert "sk-test" not in json.dumps(captured["body"])  # the key is only in the header
    assert [(s.table, s.value, s.count) for s in bp.scenarios] == [("orders", "REFUNDED", 20)]  # unknown table dropped, rule parse + AI deduped
    assert [(p.column, p.values) for p in bp.value_pools] == [("note", ["Leave at d"])]  # enum pool rejected, length-truncated
    assert bp.locale_hint == "en_IN"
    monkeypatch.undo()
    get_settings.cache_clear()
