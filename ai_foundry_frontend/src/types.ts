export type DbType = 'postgresql' | 'mysql' | 'mongodb'
export type GenMode = 'fast' | 'scenario' | 'testcase'
export type Row = Record<string, string | number | boolean | null>

export interface ConnectionRequest {
  dbType: DbType
  targetId?: string
  host?: string
  port?: number
  database?: string
  username?: string
  password?: string
  ssl?: 'disable' | 'require' | 'verify-full'
  uri?: string
  label?: string
  allowLoad?: boolean
  /** PostgreSQL schema to read from and load into (default "public") */
  schema?: string
}

export interface ApprovedTarget {
  id: string
  label: string
  dbType: DbType
  host: string
  port: number
  database: string
  loadAllowed: boolean
  schemaName?: string | null
}

export interface ConnectionResult {
  ok: boolean
  dbType: DbType
  database: string
  metadataAccess: 'Allowed' | 'Denied'
  tablesDiscovered: number
  targetId?: string
  message: string
}

export interface Column {
  name: string
  type: string
  maxLength?: number
  nullable: boolean
  primaryKey: boolean
  unique: boolean
  default?: string
  enumValues?: string[]
  check?: string
  /** Not discovered from metadata (MongoDB without validators). Shown as missing, never invented. */
  missing?: boolean
  precision?: number | null
  generated?: boolean | null
  identityAlways?: boolean | null
  scale?: number | null
}

export interface ForeignKey {
  column: string
  refTable: string
  refColumn: string
}

export interface Table {
  name: string
  columns: Column[]
  foreignKeys: ForeignKey[]
  uniqueTogether?: string[][]
  needsDefinition?: boolean
}

export interface Schema {
  dbType: DbType
  database: string
  schemaName?: string | null
  targetId?: string
  tables: Table[]
  warnings: string[]
  source: 'boomi-jdbc' | 'boomi-pymongo'
  extractedAt: string
}

export type StepState = 'pending' | 'running' | 'done' | 'failed'
export interface TraceStep {
  id: string
  layer: 'React' | 'FastAPI' | 'Boomi' | 'Database' | 'AI'
  label: string
  detail: string
}

export interface Scenario {
  table: string
  column: string
  value: string
  count: number
}

export interface TableCount {
  table: string
  count: number
}

export interface TestCaseConfig {
  /** Optional focus for the AI ("checkout and refunds"). */
  feature: string
  categories: TestCategory[]
  /** Postman collection (v2.x) or OpenAPI / Swagger text: the source of the real endpoints. */
  collectionText?: string
  /** Read a few existing rows (read-only) to use as valid values. */
  useDbSamples?: boolean
  openApiText?: string
  apiBaseUrl?: string
  selectedEndpoints?: string[]
  businessRules?: string
}

export type TestCategory = 'positive' | 'negative' | 'boundary' | 'workflow'

export interface JobConfig {
  mode: GenMode
  tables: TableCount[]
  locale: string
  seed?: number
  description?: string
  scenarios?: Scenario[]
  testCase?: TestCaseConfig
}

export interface Blueprint {
  domain: string
  localeHint: string
  tableCounts: TableCount[]
  scenarios: Scenario[]
  columnRules: { table: string; column: string; rule: string }[]
  notes: string[]
}

export interface ValidationCheck {
  id: string
  label: string
  checked: number
  failed: number
  status: 'passed' | 'warning' | 'failed' | 'skipped'
  detail?: string
}

export interface ScenarioCoverage {
  scenario: Scenario
  generated: number
  result: 'Covered' | 'Partial' | 'Missing' | 'Unsupported'
  note?: string
}

export interface RequestFixture {
  method: string
  path: string
  body?: Record<string, unknown> | null
  headers?: Record<string, string>
  /** "2xx", "4xx" or an exact code */
  expectedStatus?: string
  note?: string
}

export interface CollectionEndpoint {
  id: string
  method: string
  path: string
  name: string
  folder: string
  table: string | null
  hasBody: boolean
}

export interface ParsedCollection {
  kind: 'postman' | 'openapi'
  title: string
  baseUrl: string
  endpoints: CollectionEndpoint[]
}

export interface TestCase {
  id: string
  category: TestCategory
  title: string
  table: string
  preconditions: string[]
  steps: string[]
  expected: string
  /** true when expected behaviour needs supplied app rules / API contract */
  needsRules: boolean
  prerequisiteRecords: { table: string; key: string }[]
  /** Invalid inputs; kept as API fixtures, never loaded as valid records */
  fixture?: RequestFixture
  /** Ordered requests of a workflow case (fixture is the first one) */
  requests?: RequestFixture[]
  /** The request found in the collection, e.g. "POST /api/tasks" */
  endpoint?: string
  ready: boolean
  readinessNote: string
}

export interface TestCaseCoverage {
  byCategory: Record<TestCategory, number>
  total: number
  withPrerequisites: number
  readyToExport: number
  needingRules: number
}

export interface Report {
  jobId: string
  dbType: DbType
  database: string
  tablesDiscovered: number
  mode: GenMode
  recordsRequested: number
  recordsGenerated: number
  dataTypeValidity: number
  relationshipIntegrity: number
  uniquenessViolations: number
  status: 'completed' | 'partial' | 'failed'
  durationMs: number
  unsupportedConstraints: string[]
  adjustments: string[]
  checks: ValidationCheck[]
  perTable: { table: string; requested: number; generated: number }[]
  scenarioCoverage?: ScenarioCoverage[]
  testCoverage?: TestCaseCoverage
}

export interface Job {
  id: string
  config: JobConfig
  status: 'running' | 'completed' | 'partial' | 'failed'
  stages: { id: string; label: string; layer: string; state: StepState; detail?: string }[]
  blueprint?: Blueprint
  report?: Report
  testCases?: TestCase[]
  error?: string
}

export interface PreviewPage {
  table: string
  total: number
  page: number
  pageSize: number
  columns: string[]
  rows: Row[]
  /** test ids linked to each row for Mode 3 (keyed by row index within page) */
  links?: Record<number, string[]>
}

export type ExportFormat =
  | 'xlsx'
  | 'csv-zip'
  | 'json'
  | 'sql-postgres'
  | 'sql-mysql'
  | 'postman'
  | 'testcase-xlsx'
  | 'pytest'
  | 'mapping-report'
  | 'report-json'
  | 'report-xlsx'

export interface LoadPlan {
  target: ApprovedTarget
  tables: { table: string; expected: number }[]
}

export interface LoadStep {
  id: string
  layer: 'React' | 'FastAPI' | 'Boomi' | 'Database'
  label: string
  state: StepState
  detail?: string
}

export interface LoadJob {
  id: string
  status: 'running' | 'success' | 'failed'
  steps: LoadStep[]
  perTable: { table: string; expected: number; inserted: number; failedBatches: number; skipped?: number }[]
  warnings?: string[]
  boomiStatus: string
  verification: { countsMatch: boolean; fkValid: boolean }
}
