# app/models.py
"""Pydantic models. JSON is camelCase on the wire so the React app (src/types.ts) works unchanged."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DbType = Literal["postgresql", "mysql", "mongodb"]
GenMode = Literal["fast", "scenario", "testcase"]
TestCategory = Literal["positive", "negative", "boundary", "workflow"]
Cell = Any  # str | int | float | bool | None


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ConnectionRequest(CamelModel):
    db_type: DbType
    target_id: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = Field(default=None, repr=False)
    ssl: Optional[str] = None
    uri: Optional[str] = Field(default=None, repr=False)
    label: Optional[str] = None
    allow_load: bool = False
    db_schema: Optional[str] = Field(default=None, alias="schema")  # PostgreSQL schema name (default "public")


class ApprovedTarget(CamelModel):
    id: str
    label: str
    db_type: DbType
    host: str
    port: int
    database: str
    load_allowed: bool
    schema_name: Optional[str] = None


class ConnectionResult(CamelModel):
    ok: bool
    db_type: DbType
    database: str
    metadata_access: Literal["Allowed", "Denied"]
    tables_discovered: int
    target_id: Optional[str] = None
    message: str


class Column(CamelModel):
    name: str
    type: str
    max_length: Optional[int] = None
    nullable: bool = False
    primary_key: bool = False
    unique: bool = False
    default: Optional[str] = None
    enum_values: Optional[list[str]] = None
    check: Optional[str] = None
    missing: Optional[bool] = None
    precision: Optional[int] = None  # numeric(p, s)
    generated: Optional[bool] = None  # GENERATED ALWAYS AS (expr) STORED: never written
    identity_always: Optional[bool] = None  # GENERATED ALWAYS AS IDENTITY: needs OVERRIDING SYSTEM VALUE
    scale: Optional[int] = None


class ForeignKey(CamelModel):
    column: str
    ref_table: str
    ref_column: str


class Table(CamelModel):
    name: str
    columns: list[Column]
    foreign_keys: list[ForeignKey] = []
    unique_together: list[list[str]] = []  # composite UNIQUE constraints
    needs_definition: Optional[bool] = None


class Schema(CamelModel):
    db_type: DbType
    database: str
    schema_name: Optional[str] = None
    target_id: Optional[str] = None
    tables: list[Table]
    warnings: list[str] = []
    source: Literal["boomi-jdbc", "boomi-pymongo"] = "boomi-jdbc"
    extracted_at: str = ""

    def table(self, name: str) -> Optional[Table]:
        return next((t for t in self.tables if t.name == name), None)


class Scenario(CamelModel):
    table: str
    column: str
    value: str
    count: int = Field(ge=0)


class TableCount(CamelModel):
    table: str
    count: int = Field(ge=0)


class TestCaseConfig(CamelModel):
    feature: str = ""
    categories: list[TestCategory]
    collection_text: Optional[str] = None  # Postman collection (v2.x) or OpenAPI / Swagger: the source of the real endpoints
    open_api_text: Optional[str] = None  # older clients: same meaning as collection_text
    use_db_samples: bool = False  # read a few existing rows to use as valid values (read-only)
    api_base_url: Optional[str] = None
    selected_endpoints: Optional[list[str]] = None
    business_rules: Optional[str] = None


class JobConfig(CamelModel):
    mode: GenMode
    tables: list[TableCount] = []
    locale: str = "en_US"
    seed: Optional[int] = None
    description: Optional[str] = None
    scenarios: Optional[list[Scenario]] = None
    test_case: Optional[TestCaseConfig] = None


class ColumnRule(CamelModel):
    table: str
    column: str
    rule: str


class ValuePool(CamelModel):
    table: str
    column: str
    values: list[str]


class Blueprint(CamelModel):
    """Structured JSON the LLM must return. Python validates it against the discovered schema before use."""

    domain: str
    locale_hint: str = "en_US"
    table_counts: list[TableCount] = []
    scenarios: list[Scenario] = []
    column_rules: list[ColumnRule] = []
    value_pools: list[ValuePool] = []
    notes: list[str] = []


class ValidationCheck(CamelModel):
    id: str
    label: str
    checked: int
    failed: int
    status: Literal["passed", "warning", "failed", "skipped"]
    detail: Optional[str] = None


class ScenarioCoverage(CamelModel):
    scenario: Scenario
    generated: int
    result: Literal["Covered", "Partial", "Missing", "Unsupported"]
    note: Optional[str] = None


class PrereqRecord(CamelModel):
    table: str
    key: str


class Fixture(CamelModel):
    method: str
    path: str
    body: Optional[dict[str, Any]] = None
    headers: dict[str, str] = {}
    expected_status: Optional[str] = None  # "2xx", "4xx" or an exact code
    note: Optional[str] = None


class TestCase(CamelModel):
    id: str
    category: TestCategory
    title: str
    table: str = ""
    preconditions: list[str]
    steps: list[str]
    expected: str
    needs_rules: bool
    prerequisite_records: list[PrereqRecord] = []
    fixture: Optional[Fixture] = None
    requests: Optional[list[Fixture]] = None  # ordered chain for workflow cases (fixture is the first request)
    endpoint: Optional[str] = None  # "POST /api/tasks" as found in the collection / spec
    ready: bool
    readiness_note: str


class TestCaseCoverage(CamelModel):
    by_category: dict[str, int]
    total: int
    with_prerequisites: int
    ready_to_export: int
    needing_rules: int


class PerTable(CamelModel):
    table: str
    requested: int
    generated: int


class Report(CamelModel):
    job_id: str
    db_type: DbType
    database: str
    tables_discovered: int
    mode: GenMode
    records_requested: int
    records_generated: int
    data_type_validity: float
    relationship_integrity: float
    uniqueness_violations: int
    status: Literal["completed", "partial", "failed"]
    duration_ms: int
    unsupported_constraints: list[str]
    adjustments: list[str]
    checks: list[ValidationCheck]
    per_table: list[PerTable]
    scenario_coverage: Optional[list[ScenarioCoverage]] = None
    test_coverage: Optional[TestCaseCoverage] = None


class Stage(CamelModel):
    id: str
    label: str
    layer: str
    state: Literal["pending", "running", "done", "failed"] = "pending"
    detail: Optional[str] = None


class Job(CamelModel):
    id: str
    config: JobConfig
    status: Literal["running", "completed", "partial", "failed"] = "running"
    stages: list[Stage]
    blueprint: Optional[Blueprint] = None
    report: Optional[Report] = None
    test_cases: Optional[list[TestCase]] = None
    error: Optional[str] = None


class PreviewPage(CamelModel):
    table: str
    total: int
    page: int
    page_size: int
    columns: list[str]
    rows: list[dict[str, Any]]
    links: Optional[dict[int, list[str]]] = None


class LoadTable(CamelModel):
    table: str
    expected: int


class LoadPlan(CamelModel):
    target: ApprovedTarget
    tables: list[LoadTable]


class LoadStep(CamelModel):
    id: str
    layer: str
    label: str
    state: Literal["pending", "running", "done", "failed"] = "pending"
    detail: Optional[str] = None


class LoadTableResult(CamelModel):
    table: str
    expected: int
    inserted: int = 0
    failed_batches: int = 0
    skipped: int = 0


class Verification(CamelModel):
    counts_match: bool = False
    fk_valid: bool = False


class LoadJob(CamelModel):
    id: str
    status: Literal["running", "success", "failed"] = "running"
    steps: list[LoadStep]
    per_table: list[LoadTableResult]
    boomi_status: str = "RECEIVED"
    warnings: list[str] = []
    verification: Verification = Verification()
    error: Optional[str] = None
