# ATOM DATA FOUNDRY - Build Prompts for Claude

AI-powered synthetic test data and API test case generation. This file holds **three end-to-end prompts** (frontend, backend, Boomi) that let Claude rebuild the whole solution as it exists today. Each prompt is self-contained: an instruction block followed by the full specification, written from a line-by-line read of the current code.

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query v5, React Router v7, @xyflow/react (schema graph), Recharts, lucide-react, SheetJS (xlsx), JSZip, js-yaml, @faker-js/faker (in-browser demo engine), oxlint |
| **Frontend hosting** | Vercel (static build, SPA rewrite) |
| **Backend** | Python 3.12, FastAPI + uvicorn, Pydantic v2 (camelCase aliases), SQLAlchemy 2, psycopg 3, PyMySQL, PyMongo, Faker, NumPy, NetworkX, openpyxl, httpx, cryptography (Fernet), PyYAML |
| **Backend hosting** | Render (web service, `/health` check) |
| **Integration** | Boomi AtomSphere: two Web Services Server listener processes, one REST connection and five REST operations, built and deployed with the **Boomi Companion** skill (`bc-integration:boomi-integration`) |
| **AI** | OpenAI GPT-4o (JSON mode) for blueprints and test-case ideas; rule-based planners as fallback |
| **Data** | Aiven MySQL registry (encrypted connections, audit, verified TLS); user PostgreSQL / MySQL target databases; embedded PostgreSQL (pgserver) for tests |
| **Security** | One common HTTP Basic pair for web app, API and Boomi; Fernet-encrypted credentials; destination policy; per-browser client id (`X-Client-Id`); approval before any load |
| **Testing** | pytest (end-to-end, registry, user connections, Mode 3, fuzz over random schemas), TypeScript build, headless smoke script |

## How to use this file

1. Open a new Claude Code session in an **empty folder** for each part (or one parent folder with `ai_foundry_backend`, `ai_foundry_frontend`).
2. Paste **Prompt 2 (backend)** first, then **Prompt 3 (Boomi)**, then **Prompt 1 (frontend)** (the numbers match the section order below, not the build order). Boomi needs the backend's `/internal/*` routes to exist; the frontend can be built at any time.
3. Run the acceptance checks at the end of each prompt before moving on.
4. Keep secrets out of the prompts: put them in each project's `.env` (names are listed in the specs, values never).

### Contracts the three parts must agree on

| Contract | Value |
|---|---|
| Browser to API | JSON with camelCase fields; headers `Authorization: Basic ...` and `X-Client-Id: <uuid>`; paths under `/api/*` |
| API to Boomi | `POST {SERVER_BASE_URL}/ws/simple/executeAfmetadata` (Process A, body `{requestId, targetId, dbType}`) and `/ws/simple/executeAfload` (Process B, body `{loadId, jobId, targetId}`); HTTP Basic |
| Boomi to API | `POST /internal/registry/lookup`, `/internal/metadata`, `/internal/batch`, `/internal/load/execute`, `/internal/audit`; HTTP Basic with the common pair; requests carry ids only, never database credentials |
| Common pair | `API_USERNAME` / `API_PASSWORD` on the API, the Boomi REST connection and the sign-in form. A Boomi cloud attachment has its own listener user: set `SERVER_USERNAME` / `SERVER_TOKEN` on the API if it differs |
| Modes | `fast`, `scenario`, `testcase` |
| Open route | `GET /health` only |

---

## Prompt 1 - Frontend (React + Vite + Tailwind, Vercel)

> Copy everything from here to the end of this section into Claude.

You are a senior front-end engineer. Build the complete **ATOM DATA FOUNDRY** web app described below: a React 19 + TypeScript + Vite + Tailwind v4 single-page app with an eight-step journey (Connect, Schema, Mode, Generate, Preview and validate, Output, Result), a real HTTP client for the FastAPI backend, and a full in-browser demo engine used when `VITE_API_BASE` is empty.

Rules:
- Follow the specification below exactly: file tree, types, routes, labels, validation rules, polling intervals, colors and API contract. Where the spec says something is wrong or unfinished, apply the fixes listed under "Improvements".
- Use only the listed dependencies. Keep the code typed (turn `strict` on) and free of unused code.
- Credentials are only ever sent by the connection test call; never stored in state, logs or storage. Basic-auth credentials live in `sessionStorage`.
- Work in this order: scaffold and config, `types.ts`, API layer (`httpApi`, `auth`, mock engine), store and shell (`main`, `App`, `Layout`, `LoginGate`, `ui`), pages one by one, then build, lint and smoke test.

Improvements to apply while rebuilding:
1. Enable `strict` in `tsconfig.app.json` and fix what it reveals; add `tsx` as a devDependency for `scripts/smoke.ts` or drop the script.
2. The SSL select must default to a value that exists in its options and in the type union (use `'require'`).
3. Mode 3 must work end to end against the real backend. In demo mode, show a clear message that reading a collection needs the backend (do not silently fall back).
4. Remove dead code (unused `openTable` state, unused exports) and keep MongoDB visible but disabled with the URI form unreachable.
5. Load the Inter font or remove it from the font stack.

Acceptance checks (all must pass):
```bash
npm install && npm run build && npm run lint
npx tsx scripts/smoke.ts
```
Then run `npm run dev` with `VITE_API_BASE` empty and walk the whole journey in the demo engine (Connect with the saved demo connection, extract schema, Mode 1 generate, preview, output, finish). With `VITE_API_BASE` pointing at the running backend, sign in with the common credentials and repeat for Modes 2 and 3.

### Specification (frontend)

Project root: `D:\ai_foundry\ai_foundry_frontend` (npm package name `ai_foundry_frontend`, private, version 0.0.0, ESM `"type": "module"`).
Product name shown in UI / `<title>`: **ATOM DATA FOUNDRY** (tagline: "AI-powered synthetic test data & test case generation").

---------------------------------------------------------------------------
#### 1. Purpose and user journey

A React SPA that lets a user (a) connect to an approved test database, (b) read its schema metadata only, (c) pick one of three generation modes, (d) generate synthetic relational data or API test cases, (e) preview and validate, (f) download files or load data into a disposable PostgreSQL database after explicit approval. It talks either to a real FastAPI backend (`VITE_API_BASE` set) or to a fully in-browser "demo engine" (mock, default). Architecture claim in UI copy: React owns UI, FastAPI owns logic, Boomi orchestrates integration, AI reasons about the domain. Layers appear as coloured badges: React, Boomi, Python/FastAPI, AI, Database.

Modes (type `GenMode`):
1. `fast` – "Mode 1: Fast Test" (tag "Schema only", layer Python): schema-valid dummy records, no description needed.
2. `scenario` – "Mode 2: AI Realistic & Scenario" (tag "Primary AI"): description + optional scenario text ("30 approved timesheets…"), AI plans, Python generates.
3. `testcase` – "Mode 3: AI Test Case Generator" (tag "AI + tests"): upload Postman collection / OpenAPI, test cases written against real endpoints; no data generated/loaded; outputs Postman, Pytest, Excel.

##### Routes (BrowserRouter) and stepper
Stepper labels/numbers (STEPS in Layout.tsx): `/connect` "Connect" (1-2), `/schema` "Schema" (3), `/mode` "Mode" (4), `/generate` "Generate" (5), `/preview` "Preview & validate" (6), `/output` "Output" (7), `/result` "Result" (8). Extra route `/how-it-works` (not in stepper). `/` and `*` redirect to `/connect`.

| # | Route | What it shows / does |
|---|---|---|
| 1-2 | `/connect` | Title "Connect a database" / "Choose a database type and test the connection. Only schema metadata is read; no existing rows are retrieved." DB type cards (PostgreSQL "MVP primary target"; MySQL "Next phase"; MongoDB "Coming soon", DISABLED with title "Not available yet"). Connection details card with toggle "Saved connections" / "New connection". Button "Test connection". On success shows a dark terminal-style block (Database Type / Database Name / Connection Status: Successful / Metadata Access / Tables Discovered) and button "Extract schema via Boomi" (note "Metadata only. No row data is read."). Right column: "What happens next" (first 5 Process-A steps) or, once extracting, card "Boomi Process A: schema metadata extraction" with live 7-step timeline. On success navigates to `/schema` after a 400 ms pause. |
| 3 | `/schema` | "Schema explorer"; subtitle `${database} (${dbType}). Click a table to see its fields, keys and relationships.` Button "Choose generation mode". 4 stat tiles (Tables / collections, Fields, Relationships (sub "not discoverable" for mongodb), Metadata source: Boomi badge + "JDBC queries" or "PyMongo adapter"). Warning alerts per `schema.warnings`. Info alert "Missing information is shown as missing" listing tables that need field definitions. Left: React Flow graph; right: table detail card with fields/types/constraint badges; for `needsDefinition` tables a manual field form. |
| 4 | `/mode` | "Choose a generation mode" (subtitle "The journey is identical for every mode. Only the inputs and generated deliverables change."). Three mode cards, then mode-specific inputs, table counts editor, options (locale/seed), "Ready to generate" summary card with "Generate" button. |
| 5 | `/generate` | "Generating"; polls job every 400 ms; shows progress bar, stage timeline, AI blueprint JSON (scenario mode), auto-navigates to `/preview` 1200 ms after finish (unless failed). |
| 6 | `/preview` | "Preview & validate"; summary stat tiles; tabs (Data preview / Scenario coverage / Test cases / Quality report) depending on mode; "Choose output" button (disabled if report.status === 'failed'). |
| 7 | `/output` | "Choose output"; download grids; optional direct DB load with confirm screen "Confirm database load"; "Finish" button → `/result`. |
| 8 | `/result` | "Final result"; summary stats, downloaded files list, "Database load report" (Boomi Process B), test-readiness report (mode 3), buttons "Back to output" and "Start new session". |
| – | `/how-it-works` | Static architecture/ownership page. |

Footer on every page: "Built-in controls" (ShieldCheck icon) + "Only approved databases can be connected", "Credentials never reach the AI service or logs", "Nothing loads without your approval".

---------------------------------------------------------------------------
#### 2. Dependencies, scripts, tooling

##### package.json (exact)
scripts: `dev: vite`, `build: tsc -b && vite build`, `lint: oxlint`, `preview: vite preview`. (smoke test is run with `npx tsx scripts/smoke.ts`; `tsx` is NOT a declared dependency.)

dependencies:
- `@faker-js/faker` ^10.6.0
- `@tailwindcss/vite` ^4.3.3
- `@tanstack/react-query` ^5.105.0
- `@xyflow/react` ^12.12.0
- `clsx` ^2.1.1
- `js-yaml` ^5.5.0
- `jszip` ^3.10.2
- `lucide-react` ^1.61.0
- `react` ^19.3.1, `react-dom` ^19.3.1
- `react-router-dom` ^7.18.4
- `recharts` ^3.10.1
- `tailwindcss` ^4.3.3
- `xlsx` ^0.18.5

devDependencies: `@types/js-yaml` ^4.0.9, `@types/node` ^24.19.2, `@types/react` ^19.3.0, `@types/react-dom` ^19.3.0, `@vitejs/plugin-react` ^6.1.2, `oxlint` ^1.88.0, `typescript` ~6.0.3, `vite` ^8.3.4.

##### vite.config.ts
```ts
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
export default defineConfig({ plugins: [react(), tailwindcss()] })
```
No proxy, no alias, no base. Dev port 5173 (`.claude/launch.json` runs `npm run dev -- --port 5173`, config name "web").

##### tsconfig
- `tsconfig.json`: `{ "files": [], "references": [tsconfig.app.json, tsconfig.node.json] }`.
- `tsconfig.app.json`: tsBuildInfoFile `./node_modules/.tmp/tsconfig.app.tsbuildinfo`; target es2023; lib ["ES2023","DOM"]; module esnext; types ["vite/client"]; allowArbitraryExtensions; skipLibCheck; moduleResolution bundler; allowImportingTsExtensions; verbatimModuleSyntax; moduleDetection force; noEmit; jsx react-jsx; noUnusedLocals; noUnusedParameters; erasableSyntaxOnly; noFallthroughCasesInSwitch; include ["src"]. NOTE: `strict` is NOT set (no strict flag) – but code is written strictly typed. `erasableSyntaxOnly` => no enums / parameter properties / namespaces (the `GenContext` class uses explicit field declarations).
- `tsconfig.node.json`: same flags, lib ES2023, types ["node"], module nodenext, include ["vite.config.ts"] (scripts/smoke.ts is not included in any tsconfig).

##### .oxlintrc.json
```json
{ "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "rules": { "react/rules-of-hooks": "error",
             "react/only-export-components": ["warn", { "allowConstantExport": true }] } }
```
(Layout.tsx exports `STEPS` and `Logo` besides default; LoginGate imports Logo from Layout.)

##### index.html
`<html lang="en">`, charset UTF-8, favicon `/favicon.svg` (blue #0f52ba rounded square with white atom: centre circle r=3.2 + three ellipses rx=11 ry=4.5 rotated 0/60/120, stroke 1.6), viewport meta, title "ATOM DATA FOUNDRY", `<div id="root">`, `<script type="module" src="/src/main.tsx">`. `public/icons.svg` also exists (unused sprite, 24 lines).

##### Tailwind v4 setup
No tailwind.config file. `src/index.css`:
```css
@import "tailwindcss";
@import "@xyflow/react/dist/style.css";
@theme {
  --font-sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
  /* Layer colours taken from the BRD diagrams */
  --color-react: #0f52ba;      --color-react-soft: #e8f1fb;
  --color-boomi: #c8325f;      --color-boomi-soft: #fbe4ea;
  --color-python: #0b1030;     --color-python-soft: #e7e9f3;
  --color-ai: #6b8e0a;         --color-ai-soft: #f0f6d6;
  --color-db: #6b7280;         --color-db-soft: #f1f2f5;
  --color-ink: #0b1030;
}
html, body, #root { height: 100%; }
body { margin:0; background:#f5f7fb; color:#0b1030; font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
.react-flow__node { cursor: pointer; }
.scroll-thin::-webkit-scrollbar { height:8px; width:8px; }
.scroll-thin::-webkit-scrollbar-thumb { background:#c5cad8; border-radius:8px; }
```
Utility classes used derive from tokens: `bg-react`, `text-react`, `bg-react-soft`, `border-react/30`, `bg-boomi`, `text-ink`, `bg-ai-soft`, `bg-python-soft`, `text-python`, `bg-db-soft`, etc., plus slate/emerald/amber/red palettes from default Tailwind. Inter font is NOT loaded via link (falls back to system fonts). Hover colours hard-coded: primary `#0c44a0`, danger `#ad2750`. Info alert text colour `#0b3f91`. Chart colours: requested `#c5cad8`, generated `#0f52ba`. React Flow: edge default `#94a3b8`, highlighted `#0f52ba`, background dots `#dbe0ea`, label bg `#f5f7fb`, label text `#475569`. DB brand colours on Connect cards: PostgreSQL `#336791`, MySQL `#c77b0b`, MongoDB `#2f8f4e`.

##### Env vars (Vite)
- `VITE_API_BASE` – FastAPI origin; when truthy the real HTTP API is used, else mock. `.env.example`: `VITE_API_BASE=http://localhost:8000`. A `.env.local` exists in the working tree with a `VITE_API_BASE` value (value redacted; `*.local` is gitignored).
- `VITE_API_USERNAME` / `VITE_API_PASSWORD` – optional, dev only, pre-set Basic credentials (visible in bundle; commented out in `.env.example`).

##### Vercel
`vercel.json`: `{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }` (SPA fallback). Build command `npm run build` (tsc -b then vite build) -> `dist`. `VITE_API_BASE` must be set in the Vercel project settings at build time (it is inlined into the bundle) – should be an HTTPS FastAPI origin with CORS allowing the Vercel origin and the headers `Authorization`, `Content-Type`, `X-Client-Id`, exposing `Content-Disposition` (needed for download filename extraction; fallback filename is `atom_foundry_export`).

##### .gitignore
Standard Vite template (logs, node_modules, dist, dist-ssr, `*.local`, editor dirs).

##### scripts/smoke.ts (run `npx tsx scripts/smoke.ts`)
Imports `mockApi` and `JobConfig`. Helper `run(label, config)`: `fetchSchema('pg-placement-test')`, `createJob`, polls `getJob` every 300 ms while `status === 'running'`, prints status, `recordsGenerated/recordsRequested`, each check (`status.padEnd(7)  label - detail`), adjustments, scenarioCoverage lines, testCoverage JSON. Table list helper: 8 placement tables, 20 each, `timesheets` = n, `timesheet_reviews` = 0. Runs: (1) Fast, locale en_IN, seed 42, timesheets 200, then prints `getPreview(jobId,'timesheets',0,3).rows`; (2) Scenario with 40 timesheets and description "An Indian university placement app. Generate 30 approved timesheets, 10 pending timesheets, 5 rejected timesheets and 5 queried timesheets", then `generateMissing` and prints per-scenario `value:generated/count result`; (3) TestCase with `tables: []` and `testCase: { feature: 'Generate positive, negative and workflow test cases for student timesheet submission and supervisor approval', categories: [positive,negative,boundary,workflow] }`, prints every case `id [category] title -> expected | prereq: table:key,… (needs rules)`; then exports `xlsx, csv-zip, json, sql-postgres, testcase-xlsx, pytest, report-xlsx` printing filename and blob size; then `startLoad(fast.jobId,'pg-placement-test')`, waits 11 s, prints `getLoad` status/boomiStatus/verification; `process.exit(0)`. Uses top-level await (needs ESM). Mode 3 in the smoke test uses NO spec file (works because mock falls back to a feature-text-driven plan).

---------------------------------------------------------------------------
#### 3. File tree (one line per file)

```
ai_foundry_frontend/
  package.json, package-lock.json     deps/scripts (lock not documented)
  index.html                          Vite entry HTML, title, favicon
  vite.config.ts                      react + tailwind vite plugins
  tsconfig.json / tsconfig.app.json / tsconfig.node.json   TS project refs
  .oxlintrc.json                      oxlint rules
  vercel.json                         SPA rewrite
  README.md                           run instructions, route<->BRD step table, backend note
  .env.example / .env.local           VITE_API_BASE etc.
  .claude/launch.json                 dev-server launch config (npm run dev --port 5173)
  public/favicon.svg, public/icons.svg  static assets
  scripts/smoke.ts                    headless mock-engine smoke test
  src/main.tsx                        providers: StrictMode > QueryClientProvider > WorkflowProvider > BrowserRouter > LoginGate > App
  src/App.tsx                         Routes + Guard component
  src/types.ts                        all domain types (section 4)
  src/index.css                       Tailwind v4 import + theme tokens
  src/api/types.ts                    `Api` interface
  src/api/index.ts                    selects httpApi vs mockApi
  src/api/auth.ts                     Basic-auth credential storage + AUTH_EVENT
  src/api/httpApi.ts                  fetch-based FastAPI client
  src/api/mock/mockApi.ts             in-browser Api implementation (jobs, loads, reports)
  src/api/mock/engine.ts              seeded data generator (GenContext), dependency ordering, locales
  src/api/mock/schemas.ts             approved targets + 3 demo schemas
  src/api/mock/ai.ts                  mock "LLM": blueprint planner + test-case planner
  src/api/mock/validator.ts           validation checks, scenario coverage, unsupported constraints
  src/api/mock/exporters.ts           xlsx / csv-zip / json / sql / postman / pytest / reports builders
  src/components/Layout.tsx           header, stepper, footer, Logo, STEPS
  src/components/LoginGate.tsx        Basic-auth sign-in gate
  src/components/ui.tsx               design-system primitives
  src/components/DataPreview.tsx      paginated table preview
  src/components/SchemaGraph.tsx      React Flow ER graph
  src/components/ReportPanels.tsx     SummaryStats, ReportView, ScenarioView, TestCaseView, StatusBadge
  src/lib/download.ts                 saveBlob (anchor download)
  src/lib/openapi.ts                  parseOpenApi (JSON/YAML) – only used by mock engine
  src/pages/ConnectPage.tsx, SchemaPage.tsx, ModePage.tsx, GeneratePage.tsx, PreviewPage.tsx, OutputPage.tsx, ResultPage.tsx, HowItWorksPage.tsx
  src/store/workflow.tsx              React-context journey state
```

---------------------------------------------------------------------------
#### 4. Types (`src/types.ts`) – verbatim

```ts
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
```

Notes on types: `Row = Record<string, string|number|boolean|null>`. `PreviewPage` type name clashes in name (not in module) with `pages/PreviewPage.tsx` component; `ModePage.tsx` imports `Schema`, `Blueprint`, `ParsedCollection`, etc. `Table.needsDefinition` marks Mongo collections without validators. `TestCase.needsRules` (type) vs readiness `ready`. `Report.status` is `completed | partial | failed`; `Job.status` adds `running`.

---------------------------------------------------------------------------
#### 5. API layer

##### 5.1 `Api` interface (`src/api/types.ts`)
```ts
export interface Api {
  mode: 'mock' | 'http'
  listTargets(): Promise<ApprovedTarget[]>
  deleteTarget?(id: string): Promise<void>
  /** Resolves when the stored Basic credentials are accepted; rejects (and signals sign-in) otherwise. */
  checkAuth?(): Promise<void>
  testConnection(req: ConnectionRequest): Promise<ConnectionResult>
  /** Boomi Process A: metadata only, request carries a target id and never credentials. */
  fetchSchema(targetId: string): Promise<Schema>
  planBlueprint(schema: Schema, config: JobConfig): Promise<Blueprint>
  /** Reads a Postman collection / OpenAPI file and matches its requests to tables. Needs the backend. */
  parseCollection(text: string, schema: Schema): Promise<ParsedCollection>
  createJob(schema: Schema, config: JobConfig): Promise<{ jobId: string }>
  getJob(jobId: string): Promise<Job>
  getPreview(jobId: string, table: string, page: number, pageSize: number): Promise<PreviewPage>
  generateMissing(jobId: string): Promise<Job>
  exportFile(jobId: string, format: ExportFormat): Promise<{ blob: Blob; filename: string }>
  getLoadPlan(jobId: string, targetId: string): Promise<LoadPlan>
  startLoad(jobId: string, targetId: string): Promise<{ loadId: string }>
  getLoad(loadId: string): Promise<LoadJob>
}
```
`api/index.ts`: `export const api: Api = import.meta.env.VITE_API_BASE ? httpApi : mockApi` (decided once at module load, build-time). Also re-exports type `Api`. Mock API has NO `deleteTarget` and NO `checkAuth` (so UI hides "Remove" and LoginGate is skipped).

##### 5.2 HTTP implementation (`src/api/httpApi.ts`)
- `BASE = VITE_API_BASE` with one trailing slash removed (`''` if unset).
- `clientId()`: anonymous per-browser id stored in `localStorage['atom_client_id']`; generated as `crypto.randomUUID()` (fallback `Math.random().toString(36).slice(2)+Date.now().toString(36)`), stripped to `[A-Za-z0-9_-]`; if localStorage throws returns `'session' + random 10 chars`. It owns that browser's saved connections server-side.
- `req<T>(path, init)`: `fetch(BASE+path, {...init, headers: { 'Content-Type':'application/json', 'X-Client-Id': clientId(), ...authHeader(), ...init?.headers }})`. If status 401: `window.dispatchEvent(new Event(AUTH_EVENT))` and throw `Error('Sign in required.')`. If `!res.ok`: message default `Request failed (${status})`; try `(await res.json()).detail ?? msg` (FastAPI `detail`); if detail not a string it is `JSON.stringify`ed; throws Error(msg). Success: `res.json()`.
- `post(path, body)` = `req(path, {method:'POST', body: JSON.stringify(body)})`.
- `file(path)`: `fetch(BASE+path, { headers: { 'X-Client-Id', ...authHeader() } })` (no Content-Type, GET); 401 -> same event + `Sign in required.`; non-ok -> `Error('Download failed (${status})')`; filename from `Content-Disposition` via `/filename="?([^";]+)"?/`, default `'atom_foundry_export'`; returns `{ blob: await res.blob(), filename }`.
- Endpoints (all JSON unless noted):

| Api method | HTTP |
|---|---|
| checkAuth | `GET /api/auth/check` (response ignored) |
| listTargets | `GET /api/targets` -> `ApprovedTarget[]` |
| deleteTarget(id) | `DELETE /api/targets/{encodeURIComponent(id)}` (response body ignored but `req` still calls `res.json()` – backend must return JSON) |
| testConnection(r) | `POST /api/connections/test` body = the raw `ConnectionRequest` (this is the ONLY call carrying credentials) -> `ConnectionResult` |
| fetchSchema(targetId) | `POST /api/schema` `{ targetId }` -> `Schema` |
| planBlueprint(schema, config) | `POST /api/plan` `{ schema, config }` -> `Blueprint` |
| parseCollection(text, schema) | `POST /api/collection/parse` `{ text, schema }` -> `ParsedCollection` |
| createJob(schema, config) | `POST /api/jobs` `{ schema, config }` -> `{ jobId }` |
| getJob(id) | `GET /api/jobs/{id}` -> `Job` |
| getPreview | `GET /api/jobs/{id}/preview?table={encoded}&page={n}&page_size={n}` -> `PreviewPage` (note snake_case `page_size`) |
| generateMissing | `POST /api/jobs/{id}/generate-missing` `{}` -> `Job` |
| exportFile(id, format) | `GET /api/jobs/{id}/export?format={format}` -> binary + Content-Disposition |
| getLoadPlan | `POST /api/jobs/{id}/load-plan` `{ targetId }` -> `LoadPlan` |
| startLoad | `POST /api/jobs/{id}/load` `{ targetId, approved: true }` -> `{ loadId }` |
| getLoad(loadId) | `GET /api/loads/{loadId}` -> `LoadJob` |

Headers on every call: `X-Client-Id`, `Authorization: Basic <base64(user:pass)>` when credentials exist (plus `Content-Type: application/json` on non-file calls). The browser never talks to Boomi or the LLM directly. `schema` and load requests carry only a target id, never credentials.

##### 5.3 Auth module (`src/api/auth.ts`)
- `KEY = 'atom_basic'` in **sessionStorage** (cleared on tab close). Value is base64 of UTF-8 `username:password` (`b64`: TextEncoder -> binary string -> `btoa`).
- `setCredentials(u,p)`, `clearCredentials()` (both try/catch, swallow storage errors), `authHeader(): Record<string,string>` returns `{Authorization: 'Basic '+token}` or `{}`; token source order: sessionStorage, else `VITE_API_USERNAME`+`VITE_API_PASSWORD` (both must be set) encoded in same way.
- `export const AUTH_EVENT = 'atom-auth-required'` (window `Event`). Dispatched by httpApi on 401 and by Layout "Sign out".

##### 5.4 LoginGate (`components/LoginGate.tsx`)
Wraps `<App/>` (inside BrowserRouter). `needsAuth = api.mode === 'http' && !!api.checkAuth`. State `'checking' | 'login' | 'ok'`; initial `'checking'` if needsAuth else `'ok'` (children render immediately in mock mode). On mount (if needsAuth): `verify()` = `api.checkAuth()` -> `ok` or `login`; registers a window listener for `AUTH_EVENT` -> state `login` (cleanup on unmount). Render: `ok` -> children; `checking` -> centered text "Connecting…"; `login` -> centered Card (max-w-sm) with Logo(36), "ATOM DATA FOUNDRY", lock icon + "Sign in to the API", fields "Username" (autoFocus, autoComplete=username) and "Password" (type=password, autoComplete=current-password), error Alert, button "Sign in" (full width, loading while busy, disabled if user or pw empty). Submit: `setCredentials(user,pw)`, call `checkAuth`; success -> clear pw state, state `ok`; failure -> `clearCredentials()` and error text: if message === 'Sign in required.' then "Username or password is incorrect." else "Could not reach the API. Check that the backend is running." Note: when a 401 happens mid-session the gate switches to the login form and unmounts children (workflow state in the context provider above survives; component-local state is lost).

---------------------------------------------------------------------------
#### 6. Workflow store, routing, guards, shell

##### 6.1 `store/workflow.tsx`
React Context (`WorkflowProvider`, hook `useWorkflow()` throws "useWorkflow must be used inside WorkflowProvider" outside). State shape:
```ts
interface Workflow { connection?: ConnectionResult; schema?: Schema; mode?: GenMode; config?: JobConfig; jobId?: string; downloads: string[]; loadId?: string }
```
Initial `{ downloads: [] }`. **No persistence** (in-memory only; page reload resets journey; no localStorage). Context value (memoised on state): the state fields plus
- `update(p: Partial<Workflow>)` – shallow merge via `setState(s => ({...s, ...p}))`.
- `reset()` – `setState({ downloads: [] })` (clears everything).
- `addDownload(name)` – appends filename if not already present.
Only the approved target id (inside `schema.targetId` / `connection.targetId`) is kept; passwords/URIs never stored.

##### 6.2 `main.tsx`
`QueryClient` defaults: `queries: { retry: false, refetchOnWindowFocus: false }`. Tree: `StrictMode > QueryClientProvider > WorkflowProvider > BrowserRouter > LoginGate > App`. Imports `./index.css`.

##### 6.3 `App.tsx`
`Guard({need, to, children})`: `need` ∈ `'schema'|'config'|'job'` maps to `wf.schema`, `wf.config`, `wf.jobId`; if falsy renders `<Navigate to={to} replace />`. Routes (all nested under `<Route element={<Layout/>}>`):
- index -> `/connect`; `/connect` ConnectPage (no guard)
- `/schema` Guard schema -> `/connect`; `/mode` Guard schema -> `/connect`
- `/generate` Guard config -> `/mode`
- `/preview`, `/output`, `/result` Guard job -> `/mode`
- `/how-it-works` (no guard); `*` -> `/connect`.
Consequence: `/generate` page itself creates the job when `jobId` is unset, so reaching `/preview` needs a `jobId` set by GeneratePage. Layout's reached array reflects the same.

##### 6.4 `Layout.tsx`
- Header (white, border-b, max-w-7xl): Logo link to `/connect` with "ATOM DATA FOUNDRY" + tagline; right side: Badge (`amber` "Demo engine (in-browser)" when `api.mode==='mock'`, else `green` "Connected to FastAPI"); NavLink "How it works" (active text-react); if `api.mode==='http'` a "Sign out" button: `clearCredentials(); wf.reset(); window.dispatchEvent(new Event(AUTH_EVENT))`; if `wf.schema` a "New session" button: `wf.reset(); nav('/connect')`.
- Stepper (only when `current >= 0` i.e. pathname starts with a STEPS path; hidden on `/how-it-works`): `current = STEPS.findIndex(s => pathname.startsWith(s.path))`. `reached = [true, !!schema, !!schema, !!config, !!jobId, !!jobId, !!jobId]`. Each step is a pill button: disabled if `!reached[i]` or `i === current`; current = blue filled (`border-react bg-react text-white`), earlier steps (`i < current`) emerald with a Check icon in the number bubble and clickable, later steps white/slate; unreachable have opacity-60 + cursor-not-allowed. Small connector line between pills. Number bubble shows `n` ("1-2","3",…).
- `<main>` max-w-7xl px-6 py-8 renders `<Outlet/>`; footer described in section 1.
- `Logo({size=28})` SVG matches favicon. Exports `STEPS`, `Logo`.

##### 6.5 UI primitives (`components/ui.tsx`)
`Layer` type; `layerStyle` map (React/Boomi/Python/FastAPI/AI/Database -> soft bg + text + 30% border; FastAPI uses python colours); `LayerBadge({layer})` (unknown -> Database style); `Badge({tone: gray|green|amber|red|blue})` pill; `Card({className, tone: react|boomi|ai|python})` white rounded-xl border shadow-sm (tone changes border colour); `CardHeader({title, subtitle, right})`; `Button({variant: primary|secondary|ghost|danger, loading})` (loading shows spinning Loader2 and disables); `Field({label, hint, children})` label wrapper; `Input`, `Textarea` (min-h-24, resize-y), `Select` (shared input class: rounded-lg border-slate-300, focus ring react/20); `Alert({tone: info|success|warning|error, title, children})` with lucide icons Info/CheckCircle2/AlertTriangle/XCircle; `StepIcon({state})` (done=green check, running=blue spinner, failed=red X, pending=slate circle); `Timeline({steps})` list of `{id, layer, label, state, detail}` with LayerBadge on right, running row highlighted `bg-react-soft/60`, pending label grey; `Stat({label, value, sub, tone: green|amber|red})`; `Tabs<T>({tabs, value, onChange})` underline tabs; `Progress({value, tone: blue|green})` 0-100 clamped bar; `PageHeader({title, subtitle, actions})` h1 text-2xl.

---------------------------------------------------------------------------
#### 7. Pages and components in detail

##### 7.1 ConnectPage (`/connect`)
Constants: `DB` = [postgresql "PostgreSQL" port 5432; mysql "MySQL" 3306 note "Next phase"; mongodb "MongoDB" 27017 note "Coming soon" `disabled: true`] (default note text "MVP primary target"). `PROCESS_A` = 7 steps `{id, layer, label}`: auth(FastAPI) "Authenticate user and validate destination against approved network policy"; recv(Boomi) "Web Services Server receives metadata request (target ID, no credentials)"; valid(Boomi) "Validate request and target, reject unapproved targets"; route(Boomi) "Route by database type"; meta(Database) "Read metadata only: information_schema / PyMongo validators. No rows are read"; norm(Boomi) "Normalize metadata JSON and return to FastAPI"; store(FastAPI) "Normalize and store unified schema model for the job".

State: `dbType` (default 'postgresql'), `source` ('registered'|'manual', default 'manual'), `targetId`, `label`, `pgSchema` ('public'), `allowLoad` (false), form `f = {host:'', port:'5432', database:'', username:'', password:'', ssl:'prefer' (typed 'disable'|'require'|'verify-full'), uri:''}`, `result?: ConnectionResult`, `steps?`, `timer` ref (interval id).
Queries: `useQuery(['targets'], api.listTargets)`; `forType` = targets of current dbType; `target` = selected one.
Effects: (1) on dbType change: clear result, set port to the DB's default and blank password. (2) on `[dbType, targets.data]`: keep `targetId` if still in `forType`, else first of `forType` (or undefined); if `forType` empty -> `source='manual'` (so a refreshed target list after a successful test does not wipe the test result). (3) unmount clears the interval.
Mutations:
- `test` -> `api.testConnection(req)`; onSuccess: `setResult(r)`, if `r.ok` refetch targets, then ALWAYS blank `password` and `uri` in state; onError: result = `{ok:false, dbType, database:'', metadataAccess:'Denied', tablesDiscovered:0, message: e.message}`.
- `extract` -> sets all 7 steps `pending`; starts a 300 ms interval that marks step k `done` if k<i, `running` if k===i, else pending, incrementing `i` until the last step (it then stays running); awaits `api.fetchSchema(result.targetId)`; finally clears the interval. onSuccess: all steps `done`, `wf.update({schema, connection: result, config: undefined, jobId: undefined, mode: undefined, downloads: [], loadId: undefined})`, wait 400 ms, `nav('/schema')`. onError: any `running` step -> `failed`; error Alert shows `extract.error.message` inside the Boomi card.
`submit()`: clear result & steps; if `source==='registered' && targetId` -> `test.mutate({dbType, targetId})`; else if mongodb -> `{dbType, uri: f.uri, label: label||undefined}`; else `{dbType, host, port: Number(port), database, username, password, ssl, label||undefined, allowLoad, schema: dbType==='postgresql' ? (pgSchema.trim()||'public') : undefined}`.
Enable rule `canSubmit`: manual ? (mongodb ? !!uri : !!(host && database && username)) : !!targetId. (Password is NOT required client-side.)
UI: DB cards (`disabled` MongoDB: opacity-50, not-allowed, tooltip "Not available yet"; its code paths — URI field, Mongo submit — remain but unreachable via UI). Connection card subtitle: "Enter your own test database. Credentials are used to connect, then stored encrypted on the server. Only a connection id comes back to the browser." Segmented toggle "Saved connections" / "New connection" (switching clears result). Saved list: each row (KeyRound icon, `label`, mono `host:port/database` plus ` (schema X)` when `schemaName && !== 'public'`, text "credentials held server-side", and—only if `api.deleteTarget` exists—a "Remove" span that calls `deleteTarget(id)` (stopPropagation) then refetches targets). Empty: info Alert `No saved connection for this database type yet. Use "New connection".` Manual form (non-Mongo): Hostname (placeholder db.example.com), Port (number), Database name (placeholder placement_test_db), **Schema** (PostgreSQL only; hint "Tables are read from and loaded into this schema only."; placeholder public), SSL mode select (Disable / Require / Verify full certificate -> values `disable|require|verify-full`), Username, Password (type password, autoComplete new-password). Below (manual only): "Connection name (optional)" (placeholder "Placement test DB"); PostgreSQL-only checkbox "This is a disposable test database. Allow loading generated data into it (you still approve every load)." (`allowLoad`); info Alert "Destinations are checked by the network policy: private networks and cloud-metadata addresses are refused. Use a database reachable from the internet." Button "Test connection" (Plug icon, loading while pending); for registered shows `Target: {database}`.
Result card: ok -> mono pre block:
```
Database Type: <PostgreSQL|MySQL|MongoDB label>
Database Name: <database>

Connection Status: Successful
Metadata Access: <Allowed|Denied>
Tables Discovered: <n>
```
+ "Extract schema via Boomi" button; failure -> error Alert titled "Connection failed" with message. Right column: steps timeline card (title "Boomi Process A: schema metadata extraction", subtitle "Live progress of the metadata workflow") or "What happens next" numbered list (first 5 PROCESS_A labels); plus a lock note "Credentials are never included in AI prompts, frontend logs or ordinary Boomi documents. After a test they are cleared from the form."

##### 7.2 SchemaPage (`/schema`)
State `selected` (default first table). `TableDetail` card: header `table.name`, subtitle "{n} fields, {m} relationship(s)"; table Field/Type/Constraints (type shown as `type(maxLength)`; key icon for PK, link icon for FK columns). Badges: `PK` (amber), `FK → refTable.refColumn` (blue), `unique` (if unique && !PK), `required` (if !nullable && !PK), `default X`, `enum: A | B` (green), `check: …` (amber). If `table.needsDefinition`: warning Alert "Fields not discovered" ("No schema validator exists for this collection. Define its fields manually; they are marked as user-defined, not discovered.") and a form: text input "field name", select type (`string,int,double,boolean,date`), checkbox "required", Plus button (disabled when name blank) -> `onAddField({name: trimmed, type, nullable, primaryKey:false, unique:false})` which does `wf.update({schema: {...schema, tables: schema.tables.map(t => t.name===selected ? {...t, columns:[...t.columns, c]} : t), warnings: schema.warnings}})`. (needsDefinition flag is never cleared after adding fields.) `incomplete` = tables with `needsDefinition && columns.length <= 1`.

##### 7.3 SchemaGraph (React Flow `@xyflow/react`)
Custom node type `table` (w-52): header (table name truncated + column count; blue filled when selected, else python-soft), first 5 columns (KeyRound amber for PK, Link2 blue for FK columns, name, type right-aligned grey), "+N more" row, amber "fields missing" row if `needsDefinition`; Handles: target on Left, source on Right.
Layout (`layout(tables)`): level(t) = 0 if no parents else `max(level(parent)) + 1` over FK parents excluding self-references (cycle guard: if table already on the recursion stack returns 0; memoised); position `x = level*320`, `y = indexWithinLevel*190` (rows counted per level in `tables` order). Edges: one per non-self FK, id `${refTable}-${table}-${column}`, `source=refTable`, `target=table`, label = FK column (fontSize 10), stroke `#94a3b8` width 1.2, or `#0f52ba` width 2 and `animated` when selected table is either endpoint; marker ArrowClosed `#94a3b8`. `ReactFlow` props: `nodes`, `edges`, `nodeTypes`, `onNodeClick -> onSelect(node.id)`, `fitView` padding 0.15, `minZoom=0.3`; children `<Background gap=20 color=#dbe0ea/>`, `<Controls showInteractive={false}/>`. Container `h-[560px]` rounded border bg-slate-50. Nodes draggable. Memoised on `[schema, selected]` (so dragging positions reset when selection changes).

##### 7.4 ModePage (`/mode`)
Local state: `mode` (initial `wf.mode ?? 'fast'`), `counts: Record<table, number>` (initial `defaultCounts`), `enabled` per table, `locale` 'en_IN', `seed` '', `description`, `advanced`, `feature`, `cats` (all four categories), `rules`, `specText`, `spec?: ParsedCollection`, `specErr`, `useSamples` false, `baseUrl`, `picked: string[]` endpoint ids, `bp?: Blueprint`.
`defaultCounts(schema)`: depth of each table = 0 if no non-self FK parents (cycle-guarded), else max(parent depth)+1; count = `[10, 50, 100][min(depth,2)]`; tables with `needsDefinition && columns.length <= 1` get 0 and start unchecked (`enabled=false`, "blocked").
`text = [description, advanced].filter(non-blank).join('. ')`. `tableList = schema.tables.map(t => ({table, count: enabled ? Number(counts)||0 : 0}))`.
`config: JobConfig` (useMemo, deps by value): `{mode, tables: tableList, locale, seed: seed.trim() ? Number(seed) : undefined, description: mode==='scenario' ? text : undefined, testCase: mode==='testcase' ? {feature, categories: cats, collectionText: spec ? specText : undefined, apiBaseUrl: baseUrl||undefined, selectedEndpoints: picked, businessRules: rules||undefined, useDbSamples: useSamples && !!schema.targetId} : undefined}`.
Validity (`valid`, enables "Generate"): fast = any table count > 0; scenario = any table count > 0 AND `text.trim()` non-empty; testcase = `!!spec && picked.length > 0 && cats.length > 0`. Hint texts when invalid: fast "Select at least one table with a count above zero."; scenario "Add an application description and at least one table."; testcase "Add your Postman collection or OpenAPI file, pick requests and at least one category."
`start()`: `wf.update({mode, config, jobId: undefined, downloads: [], loadId: undefined})`; `nav('/generate')`.
Mode cards: each shows icon (Zap / Sparkles / FlaskConical), LayerBadge (Python for fast, AI for others), "Mode N: Title", tag, 3 bullet points (see section 1; fast: "Schema-valid dummy records", "No application description needed", "Works even if the AI service is unavailable"; scenario: "Domain-specific, interconnected data", "Optional exact scenarios, statuses and counts", "AI plans the rules, Python generates"; testcase: "Drop your Postman collection or OpenAPI file", "Cases use your real endpoints, no data is loaded", "Outputs: Postman, Pytest, Excel"). Clicking sets mode and clears `bp`.
**Mode 2 panel** ("Describe the application", AI badge): "Application description" textarea (placeholder "An Indian university placement management application."), two preset chips ("An Indian university placement management application", "Indian grocery delivery app with 20 refunded orders") that overwrite description; "Advanced: scenarios and counts (optional)" textarea (hint "Combined request example: 100 students, 60 placements, 30 approved timesheets, 10 pending timesheets, 5 rejected timesheets."); secondary button "Preview interpreted plan" (calls `api.planBlueprint(schema, config)`, disabled when `text` blank; note "Schema and prompt only are sent to the AI. No credentials."). Result block "Interpreted generation plan": Locale label (`LOCALES[bp.localeHint]?.label`), badges `table: count` for counts>0, scenario list (`<count badge> table.column = **value**`) or "No explicit scenarios found. Realistic data will be generated for the domain.", notes prefixed "⚠ ", ghost button "Raise counts to cover every scenario" (sums scenario counts per table, sets each `counts[t] = max(need, current)` and enables those tables).
**Mode 3 panel**: card "Your API: Postman collection or OpenAPI" (AI badge; subtitle "Test cases are written against the real requests in this file. The connected database supplies the field rules (required, unique, lengths, enums)."): file input label "Upload collection (.json) or OpenAPI (.json / .yaml)" (accept `.json,.yaml,.yml`; reads `file.text()` -> `loadSpec(text)`; resets input value); "Reading…" while parse pending; once parsed a green Badge `{Postman|OpenAPI}: {title}, {n} requests, {m} matched to tables`; a monospace textarea "…or paste the collection / specification here" (on blur, if non-blank and not yet parsed and not pending -> `loadSpec`). `loadSpec(t)`: set text, clear spec & error, if non-blank run `readSpec.mutate(t)` = `api.parseCollection(t, schema)`; success: set spec, clear err, `baseUrl = p.baseUrl.startsWith('http') ? p.baseUrl : ''`, `picked = all endpoint ids`; error: spec undefined, picked [], `specErr` shown as error Alert. When spec present: input "API base URL (optional)" (hint "Leave empty to use a {{baseUrl}} variable in the exported Postman collection."; placeholder https://test-api.example.com); endpoint list header "Requests to write tests for ({picked} of {total})" with All/None links; scrollable (max-h-64) checkbox rows each showing method Badge (blue), mono path, truncated name, and on the right the matched table Badge (green) or amber "no table matched". Warning line if any endpoint has `!table && hasBody`: "Requests with no matching table still get tests, but field rules (required, lengths, enums) are unknown, so fewer cases are written."
Card "What to test": category checkboxes Positive / Negative / Boundary / Workflow (`TestCategory`); "Focus (optional)" textarea (hint "Guides the AI towards what matters, for example refunds or approvals."; placeholder "Student timesheet submission and supervisor approval."); "Application rules (optional)" textarea (hint "Permissions and duplicate handling cannot be inferred from a schema. Supplying rules makes those cases ready to export."); checkbox **"Use a few existing rows from my database as valid values"** (description: "Read-only: up to 5 rows from the tables behind the selected requests. Used for real parent ids and for duplicate-value tests. Nothing is written. Leave off if the data is sensitive.") – disabled/greyed when `!schema.targetId`; value sent as `useDbSamples: useSamples && !!schema.targetId`. In Mode 3 the right column shows a "How test cases are built" explainer instead of Options, and the record-counts editor is hidden; the "Ready to generate" card omits "Records requested".
**Counts editor** (modes 1 & 2): card "Tables and record counts" (subtitle "Select tables and set the number of records for each. Parent tables are added automatically when required."), All/None links, per-table row: checkbox, name, text "{n} fields, depends on a, b" or (blocked) "Fields not defined, define them in the schema explorer", number input (min 0, w-28, disabled when unchecked).
**Options card** (modes 1 & 2): Locale select from `LOCALES` (imported from `api/mock/engine` even in http mode: en_IN "English (India)", en_US "English (US)", en_GB "English (UK)", de "German", fr "French"), "Generation seed (optional)" number input (hint "Use the same seed to repeat a dataset exactly.", placeholder "e.g. 42").
"Ready to generate" card (tone react): Mode title, Records requested (sum of table counts; not in mode 3), "AI required": No for fast else Yes, full-width "Generate" button.

##### 7.5 GeneratePage (`/generate`)
On first mount (guarded by a `started` ref so StrictMode doesn't double-run) and if `wf.jobId` unset: `api.createJob(wf.schema!, wf.config!)` -> `wf.update({jobId})`, errors into local `err`. `useQuery(['job', jobId], api.getJob, enabled: !!jobId, refetchInterval: running-or-no-data ? 400 : false)`. `pct` = done stages / total stages *100. When `done` (status !== 'running') and not failed: after 1200 ms `nav('/preview')` (timer cleaned up). Title "Generating"; subtitle `${modeName}. AI plans, Python creates and validates. Nothing is written to a database at this stage.` Error alert "Generation could not start". Left card: header `Job {id}` or "Starting job…" with status Badge (blue running / red failed / amber partial / green); Progress bar (green when done); Timeline of `job.stages`; job.error alert. Right: if `blueprint` – card "AI generation blueprint" ("Structured JSON returned by the model and validated by Python") with JSON pretty-print in scrollable `<pre>`; success alert "Generation finished" / "Opening the preview and validation report…" when done & not failed; when done: buttons "Open preview" and secondary "Back to mode". Note: if the user revisits `/generate` with an existing jobId it will not create a new job (shows the old one).

##### 7.6 PreviewPage (`/preview`)
`useQuery(['job', jobId], getJob)` once (no polling). Tab state initial `'tests'` for mode 3 else `'data'`. Error -> alert "Job unavailable"; no report -> "Loading report…". Title "Preview & validate"; subtitle by mode (mode 3: "Review the generated test cases and their requests, then export them."; else "Review 20 records per table, the validation results and coverage before choosing an output."). Action "Choose output" disabled when `report.status==='failed'`; failed alert "Validation failed" / "Fix the failing checks and regenerate. Export and load are disabled." `<SummaryStats r>`. Tabs (not rendered in mode 3): "Data preview" (mode≠3), "Scenario coverage" (mode scenario only), "Test cases" (mode 3), "Quality report" (mode≠3). Content: data -> `DataPreview`, scenarios -> `ScenarioView` (onChanged invalidates `['job', jobId]`), tests -> `TestCaseView` (if `report.testCoverage`), report -> `ReportView`. (`openTable` state is a constant `undefined`.)

##### 7.7 DataPreview
Props `{job, schema, initialTable}`. `PAGE = 20`. Tables = `report.perTable` where `generated > 0`; sidebar card "Tables" (name + count). `useQuery(['preview', job.id, table, page, report.recordsGenerated], api.getPreview(job.id, table, page, 20), enabled: !!table, placeholderData: prev)`. Page resets to 0 on table change. Header `"{table} preview"`, subtitle `{min(20,total)} of {total} records, retrieved page by page`, prev/next chevrons, "Page X of Y". Shows relationship Badges `col → refTable.refColumn` (from schema FKs), and Badges for any `failed`/`warning` checks (`label: detail`). Table: optional first column "Test IDs" with green Badges when `data.links` present (mode 3 prerequisite linkage); FK columns get a small Link2 icon in the header; cells truncated (`max-w-56`, `title` full value), `null` rendered as grey "null".

##### 7.8 ReportPanels
- `StatusBadge({status})`: green "completed", amber "partially completed", red "failed".
- `SummaryStats({r})`: mode 3 (`r.mode==='testcase' && r.testCoverage`): 4 tiles — "Status" (badge, sub `{durationMs/1000 to 1 dp}s`), "Test cases" (`total`, sub `{readyToExport} ready to run`), "By category" (`pos / neg / bound / workflow`, sub "positive / negative / boundary / workflow"), "Records written to your database" (0, green, sub "none generated, none loaded"). Otherwise 5 tiles: "Generation status", "Records generated" (toLocaleString; sub `of N requested`; amber if generated<requested), "Data-type validity" (`{x}%`, green if 100 else red), "Relationship integrity" (same), "Uniqueness violations" (green if 0 else red).
- `ReportView({r})`: optional warning Alert (title "Notes" in mode 3 else "Requested counts could not be met exactly") listing `adjustments`; card "Validation checks" (subtitle mode 3: "Run against your collection and the database rules", else "Run against the generated dataset before any insert is offered") listing each check with icon (passed green check, warning amber triangle, failed red X, skipped grey minus), label, detail, and right text Passed/N/A/Warning/Failed; Recharts BarChart "Requested vs generated" (mode≠3; `perTable`, X `table` angled -20°, bars `requested` #c5cad8 and `generated` #0f52ba, legend, tooltip, h-64); "Report details" definition list (Database type, Database, Tables discovered, Generation mode label {fast:"Fast Test", scenario:"AI Realistic & Scenario", testcase:"AI Test Case Generator"}, Records requested/generated (not mode 3), Execution duration `x.xx s`); card "Unsupported constraints" ("Rules that are not automatically validated or could not be discovered") list or "None."
- `ScenarioView({job, onChanged})`: card tone ai "Scenario coverage report" ("Requested workflow scenarios against records actually generated"); button "Generate missing scenarios" (visible when any coverage is `Missing` or `Partial`) -> `api.generateMissing(job.id)` then `onChanged`. Empty coverage text: "No explicit scenarios were requested. Realistic data was generated for the described domain." Table columns: Requested scenario (`Value-capitalised` + ` ` + table with `_`→space, e.g. "Approved timesheets"), Requested, Generated, Result badge (Covered green, Partial amber, Missing red, Unsupported gray), Note. Error alert on mutation error.
- `TestCaseView({job})`: left card "Test case coverage report" (rows `{category} tests` count, Total) + disclaimer "Generated-test count is not code coverage and is not proof that an API passed these tests. Expected statuses are 2xx / 4xx classes unless your collection documents an exact code."; right three stats: "Requests covered" (distinct `endpoint` count; sub `{n} multi-step workflows` = cases with `requests?.length`), "Ready to export" (green), "Need rules / API contract" (amber if >0; sub "schema alone cannot define expected behaviour"). Card "Generated test cases" ("Expand a case to see its steps, expected status and the exact request") with accordion `CaseRow`s.
- `CaseRow({tc})`: collapsed row: mono id, category Badge (positive green, negative red, boundary amber, workflow blue), title, optional mono `endpoint` (lg+), Badge "Ready"(green)/"Needs rules"(amber), chevron. Expanded 3-column grid: Preconditions (or "None") + numbered Steps; Expected result, `readinessNote`, "Field rules from table {table}"; "Request"/"Requests (in order)" — a `<pre>` per request: `{method} {path}  -> expect {expectedStatus ?? '2xx'}` followed by pretty JSON body (indent 1) if any (uses `tc.requests` if non-empty else `[tc.fixture]`).

##### 7.9 OutputPage (`/output`)
State: `busy` (format being downloaded), `error`, `confirming`, `approved`. `mode = wf.config.mode`. Item grids (each card: icon, tag badge, title, description (or disabled reason), secondary "Download" button with a leading green Check if any file in `wf.downloads` lowercased includes `it.id.split('-')[0]`):
- Generated data (mode≠3): xlsx "Excel (.xlsx)" ("One workbook, one sheet per table", tag MVP); csv-zip "CSV ZIP" ("One CSV per table plus schema manifest and validation report"); json "JSON" ("Grouped synthetic records"); sql-postgres "PostgreSQL .sql" (disabled unless `schema.dbType==='postgresql'`: "Available for PostgreSQL schemas"); sql-mysql "MySQL .sql" (tag "MySQL phase"; disabled unless mysql); `archive` "Native database archive" (tag "Future", always disabled: "Planned for a later phase. A SQL script is not a pg_dump archive.").
- Test case deliverables (mode 3, card tone ai): testcase-xlsx "Test case workbook"; postman "Postman Collection" ("… (v2.1)"); pytest "Pytest files" ("httpx-based tests; set BASE_URL and AUTH_TOKEN, workflow tests chain the created id", tag Optional); mapping-report "Endpoint coverage".
- Reports (mode≠3): report-json "Report (JSON)", report-xlsx "Report (Excel)".
Download: `api.exportFile(jobId, f)` -> `saveBlob(blob, filename)` (lib/download: object URL + temporary `<a download>` click, revoke after 1000 ms) -> `wf.addDownload(filename)`; error -> alert "Export failed".
Direct DB load card (mode≠3; tone boomi): title "Direct test database load" ("Optional. Boomi Process B orchestrates the load and the Python adapter inserts parents first."). Button "Review load" (danger) enabled only if `target?.loadAllowed`, where `target = targets.find(t => t.id === schema.targetId)` from `useQuery(['targets'])`. Otherwise explanatory text: no target -> "Saved connection not found. Go back to Connect and test the connection again."; non-postgres -> "Direct load is available for PostgreSQL databases only (MySQL and MongoDB are planned). You can still download the files."; else "This connection was saved without "allow loading". Go back to Connect, tick "This is a disposable test database. Allow loading…" and test the connection again. Only do this for a database you are happy to insert test rows into." When loadable shows `Target: {label}` + ` (schema X)`.
**Load approval flow**: "Review load" sets `confirming` -> page replaced by "Confirm database load" ("Nothing is loaded without your approval. Review the target and counts."): card tone boomi "Approved target environment" with label and mono `host:port/database`; `useQuery(['loadplan', jobId, target.id], api.getLoadPlan, enabled: confirming && target)` lists tables ("Affected tables, loaded parents first") with `{n} records` and Total; "Preparing plan…" while loading; info alert "Orchestrated by Boomi Process B. The load is reported as successful only after counts and foreign keys are verified."; checkbox "I approve inserting these synthetic records into **{database}**."; buttons: danger "Approve and load" (enabled only when `approved && plan.data`; loading while mutation pending) -> `api.startLoad(jobId, target.id)` -> `wf.update({loadId})` + `nav('/result')`; secondary "Cancel" (resets confirming/approved). Mutation error alert shown. Header action "Finish" (secondary) -> `/result`. Header subtitle mode 3: "Download the test cases as a Postman collection, Pytest files or a workbook." else "Download files or load approved records into the test database."

##### 7.10 ResultPage (`/result`)
`useQuery(['job'])` (no polling) and `useQuery(['load', loadId], getLoad, enabled: !!loadId, refetchInterval: running/no-data ? 500 : false)`. "Loading result…" until report exists. Subtitle: loadId ? "Load status and readiness report." : "Your files are ready. Nothing was loaded into a database." Actions "Back to output" and primary "Start new session" (`wf.reset(); nav('/connect')`). `SummaryStats`. Card "Downloaded files" (count Badge; list of filenames with Download icon, or "No files downloaded yet. Go back to the output step to download."). Card "Database load report" ("Boomi Process B"; status badge SUCCESS/FAILED/RUNNING; "No load was requested." if none): Timeline of load steps; per-table rows `{inserted} / {expected} inserted` + `, N skipped` + `, N failed batch(es)` with green Progress `((inserted+skipped)/expected*100)`; grid: Boomi status, Counts match (… while running, Yes/No), Foreign keys valid; warnings alert "Some records were skipped" (list); success alert "Load verified" ("Reported as successful only after expected and actual counts matched and foreign keys were checked."); failed alert "Load verification failed" ("The loaded data did not match the approved dataset."). For mode 3 (when `testCases` and `testCoverage`): card "Test-readiness report" with Cases generated, Ready to export, Requests covered, "Waiting on rules / API contract" and footnote "This reports readiness to execute. It is not proof that the API passed these tests." Closing card: "Results come from actual generation and validation against the discovered schema, not preset success messages."

##### 7.11 HowItWorksPage
Static: title "How ATOM DATA FOUNDRY works"; 8-step flow cards (Connect database/React, Extract schema metadata/Boomi, Display schema/React, Select a mode/React, Generate/AI, Preview & validate/React, Choose output/React, Final result/React with descriptions), "Technology ownership" list (React, Boomi, Python, AI, Database), "Generation pipeline" chips (Validated schema → Mode rules → Dependency graph → Parent records → Child records → Scenario rules → Validate all → Store dataset) with note "Nine checks run before any insert is offered: data type, required fields, string length, primary key, foreign key, unique constraint, enum and check constraints, scenario counts, test-case linkage.", and "Backend connection" card explaining `VITE_API_BASE` and `src/api/httpApi.ts`.

##### 7.12 `lib/openapi.ts`
`parseOpenApi(text)`: if text starts with `{` JSON.parse else `js-yaml` `load`; throws `No "paths" found. Is this an OpenAPI / Swagger document?` when no `paths`; collects endpoints for methods get/post/put/patch/delete -> `{method: UPPER, path, summary: summary ?? operationId ?? ''}`; `baseUrl = servers[0].url` or (swagger2) `${schemes[0] ?? 'https'}://${host}${basePath ?? ''}`; `title = info.title ?? 'API'`. Used only by `mockApi.generateTestCases` (and not by any UI code path since UI sends `collectionText`).

---------------------------------------------------------------------------
#### 8. In-browser mock engine (`src/api/mock/*`)

##### 8.1 `schemas.ts`
`APPROVED_TARGETS` (ApprovedTarget[]):
- `pg-placement-test` "Placement test DB (PostgreSQL)", postgresql, host `placement-test.atom.internal`:5432, db `placement_test_db`, loadAllowed true
- `mysql-retail-test` "Retail test DB (MySQL)", mysql, `retail-test.atom.internal`:3306, `retail_test_db`, loadAllowed false
- `mongo-support-test` "Support test DB (MongoDB)", mongodb, `support-test.atom.internal`:27017, `support_test_db`, loadAllowed false
Helpers `col`, `pk(name,type='serial')` (primaryKey+unique), `fk`, `tbl`. Schemas:
- **placement** (PostgreSQL, warning "Check constraints are read from pg_constraint; only simple range checks are validated automatically.", source `boomi-jdbc`): universities(university_id serial PK; name varchar120 unique; city varchar80; country varchar60; established_year integer check "established_year BETWEEN 1800 AND 2025"; contact_email varchar120); departments(department_id; university_id int FK->universities; name varchar100; head_name varchar100 nullable); students(student_id varchar12 PK; university_id FK; department_id FK->departments; full_name; email unique; phone nullable; enrolment_year integer check ">= 2015"; is_active boolean default 'true'); placement_providers(provider_id; name unique; industry; city; contact_email; phone nullable); supervisors(supervisor_id varchar12 PK; provider_id FK; full_name; email unique; is_authorized boolean default 'true'); placements(placement_id varchar12 PK; student_id FK; provider_id FK; supervisor_id FK; role_title; start_date date; end_date date nullable; status enum ACTIVE/COMPLETED/CANCELLED); timesheets(timesheet_id varchar12 PK; placement_id FK; student_id FK; week_start date; hours_worked numeric check "hours_worked >= 0 AND hours_worked <= 60"; status enum SUBMITTED/PENDING/APPROVED/REJECTED/QUERIED; notes text nullable; submitted_at timestamp); timesheet_reviews(review_id serial PK; timesheet_id FK; supervisor_id FK; decision enum APPROVED/REJECTED/QUERIED; reviewed_at timestamp; comment text nullable).
- **retail** (MySQL, warning "MySQL check constraints below 8.0.16 are parsed but not enforced by the engine."): customers, products(price check "price > 0"; sku unique), orders(status enum PLACED/PAID/SHIPPED/DELIVERED/CANCELLED/REFUNDED), order_items(quantity check "quantity > 0"), payments(method enum UPI/CARD/NETBANKING/COD; paid_at nullable).
- **mongo** (source `boomi-pymongo`; warnings about unknown cross-collection references and "Collection "audit_logs" has no schema validator. Provide a JSON Schema or define its fields manually."): users(_id objectId, name, email unique, plan enum FREE/PRO/ENTERPRISE, created_at date), tickets(_id, subject maxLength150, priority LOW/MEDIUM/HIGH, status OPEN/IN_PROGRESS/CLOSED, opened_at date), audit_logs(only `_id`, `needsDefinition: true`).
`buildSchema(targetId)` returns `{targetId, extractedAt: now ISO, dbType, database, tables, warnings, source}`; default branch = placement/postgres.

##### 8.2 `engine.ts`
- `LOCALES`: en_IN (default), en_US, en_GB, de, fr -> `fakerEN_IN/EN_US/EN_GB/DE/FR` from `@faker-js/faker` v10 (shared singleton instances; seeded via `faker.seed(seed ?? random)`).
- Type predicates `isInt` (serial,bigserial,integer,int,bigint,smallint,long), `isNum` (numeric,decimal,float,double,real,number), `isDate` (date,timestamp,timestamptz,datetime), `isText` (varchar,text,string,char).
- `parseRange(check)`: BETWEEN a AND b -> {min,max}; else `>=n` sets min, `>n` sets min n+1; `<=n` max, `<n` max n-1 (regexes apply to whole string).
- `dependencyOrder(tables, selected)`: Kahn topological sort over FK edges among selected tables; self refs recorded in `selfRefs` and ignored for ordering; remaining nodes = `cyclic`. Returns `{order, cyclic, selfRefs}`.
- `requiredParents(schema, selected)`: adds (recursively, mutating `selected`) FK parent tables that are required (`!col.nullable`, not self, not already selected); returns added names.
- `GenContext(schema, locale, seed, domain)`: picks faker by locale (fallback en_US); `domainKey` = 'placement' if domain text matches `/placement|universit|student|college|intern/` or schema has table `timesheets`; 'commerce' if `/grocery|commerce|retail|shop|order/` or table `order_items` exists (commerce overrides). Domain lists for industry/department/role (placement) and category/product (commerce). 
  - Value generation order per column (`addRow`): forced values; FK parent values from explicit `parents` map; "anchor FKs" (if a parent table also references a table this table references directly, pick one parent row and derive the sibling column from it for coherence); PK -> `nextKey` (objectid -> 24 hex lowercase; uuid; integer types -> counter+1; otherwise `{PREFIX}{101+idx}` with PREFIX map students STU, placements PLC, timesheets TS, supervisors SUP, else first 3 letters upper); FK -> random existing parent row's ref column (self-reference uses same table rows; null if none); nullable -> 15% null; else `fromColumn`: enum -> random value; name-based hints (`email` -> faker email lowercase, `phone`, `city`, `country` by locale, `industry`, `category`, `sku` `SKU-XXXXXXXX`, `role_title`, `head_name`/`*full_name`/user-ish `name` -> person name, `name` per table (universities "<City> University/Institute of Technology/College of Engineering", departments list, products list, provider/company -> company name, else productName), `subject`, `notes/comment/description` -> lorem sentence); unique hints made unique via `uniq` (up to 40 attempts appending attempt number, truncating to maxLength, then fallback suffix `-N`); boolean (p=0.9 if default 'true' else 0.5); ints/numerics via `numeric` (range from check; heuristics: year 2015-2025, hours 10-45, price/amount 49-4999, stock/quantity 1-50; default 0-1000; one-sided checks extend +1000; floats 2 dp); date -> within last 300 days (`YYYY-MM-DD`), timestamps ISO; text -> 1-3 lorem words truncated to maxLength (unique -> suffixed). Result strings truncated to `maxLength`.
  - Post-fix date coherence: `end_*` = `start_*/week_start` + 60-180 days (unless forced); `submitted_at` = start/week_start + 5-7 days; `reviewed_at` = parent timesheet's `submitted_at` + 1-4 days.
  - `sampleRow(table, forced)`: build a row without keeping it (pops row and restores counter) for request fixtures. `pkOf`. `createChain(table, forced, depth, created)`: creates row + fresh parent rows `depth` levels up (anchor FKs first to keep sibling coherence); deeper ancestors reuse existing rows; records `{table, key}` in `created`.

##### 8.3 `ai.ts` (mock LLM)
- Alias matching: table name words, all suffixes and singularised last word (ies->y, trailing s removed); `findTable(schema, text)` returns table whose alias is a suffix of the phrase (longest alias first) plus the leftover prefix.
- `planBlueprint(schema, config)`: splits description on `, ; \n`, word `and`, and sentence periods; each clause matched with `(?:generate|create|add|include|with)?\s*(\d[\d,]*)\s+(.+)`; if table found and no leftover prefix -> table count override; if leftover (e.g. "approved") -> scenario `{table, column, value: LASTWORD.toUpperCase(), count}` where column = first column whose enumValues contain the value (case-insens) else column named `status`. `domain` = trimmed description or "Generic application (no description supplied)"; `localeHint`: /india/ -> en_IN, uk/british/england -> en_GB, else `config.locale`. `columnRules`: for enum non-PK columns "Weighted choice over A / B / C" (max 8). `notes`: unique-email note, scenario-total-exceeds-count notes, "No application description given…". `tableCounts` = map of config tables' counts (overridden).
- `planTestCases(schema, feature, categories, ctx, endpoint?)`: target table = best alias match of focus text (score 100+len if matched, + FK count + 2 if has `status` enum). Path = endpoint.path or `/api/v1/{table-with-dashes}`. Generates cases `TC001…`: positive (valid create; without optional fields; per status value (2)); negative (missing each required FK (up to 3) -> 422; non-existent FK parent -> 409/422; negative numeric (2); wrong type for a text column; duplicate (needsRules, prereq row); unauthorized approval (needsRules) for `timesheets` or tables with status enum); boundary (numeric min/max/just-above-max from check ranges (2 numeric cols), string one over maxLength, date set to today); workflow (status transitions from initial state -> approved/rejected/queried etc., up to 4, PATCH `{path}/{id}`; end-to-end create then retrieve). Each case: `{id, category, title, table, preconditions, steps, expected, needsRules, prereq:{kind: parents|row|none}, fixture:{method,path,body}}`.

##### 8.4 `validator.ts`
`validate({schema, dataset, coverage, testCases})` returns 9 `ValidationCheck`s in order: `type` "Data type matches field"; `required` "Required fields not null" (null allowed if nullable or `missing`); `length` "String length within limit"; `pk` "Primary key unique"; `fk` "Foreign key references a parent" (null skipped; self-refs checked in same table); `unique` "Unique constraint holds"; `enum` "Enum and check constraints" (enum membership and numeric range from `parseRange`); `scenario` "Scenario counts match request" (warning if any scenario not Covered; `skipped` "No scenarios requested" otherwise); `linkage` "Test-case linkage exists" (failed if a case's prerequisite records are absent from dataset; `skipped` "Mode 3 only" if no test cases). Status failed if any failures (except scenario = warning). Detail default `"{n} values checked"` / `"{f} of {n} checked values failed"`. `scenarioCoverage(dataset, schema, scenarios)`: `Unsupported` if schema lacks table/column or value not in enum; else count rows with case-insensitive equality; `Covered` (>= count), `Missing` (0), `Partial`; note "{n} more required." `unsupportedConstraints(schema)`: check constraints not parseable as a range ("… check "…" is not automatically validated"), `needsDefinition` tables ("no validator, fields were not discovered"), mongo cross-collection note.

##### 8.5 `exporters.ts` (`buildExport(format, input)`)
Filename stamp `atom_foundry`. `xlsx` (SheetJS `xlsx`, one sheet per table, sheet name sliced to 31) -> `atom_foundry_data.xlsx`; `csv-zip` (JSZip: `{table}.csv` per table with schema column order, `schema_manifest.json` {database, dbType, tables, loadOrder}, `validation_report.json`, plus `test_case_data_mapping.csv` when test cases) -> `atom_foundry_data.zip`; `json` -> `atom_foundry_data.json` ({table: rows}); `sql-postgres` -> `atom_foundry_postgres.sql` (header comments, `BEGIN;`, chunks of 100-row multi-row INSERTs in load order with `"quoted"` identifiers, `COMMIT;`); `sql-mysql` -> `atom_foundry_mysql.sql` (backtick quoting, `BEGIN;` replaced with `START TRANSACTION;`); `testcase-xlsx` (sheets "Test cases" and "Data mapping") -> `atom_foundry_test_cases.xlsx`; `postman` -> `atom_foundry_postman_collection.json` (v2.1.0 collection, variable `baseUrl`, one item per case with a fixture; test script asserts 400-499 when expected text matches `/\b4\d\d\b|error|denied/i` else 200-299); `pytest` -> `test_atom_foundry.py` (httpx tests, `BASE_URL` env); `mapping-report` -> `atom_foundry_test_data_mapping.xlsx`; `report-json` -> `atom_foundry_report.json`; `report-xlsx` (sheets Summary, Checks, Per table, optional Scenario coverage) -> `atom_foundry_report.xlsx`. SQL literals: NULL, numbers raw, booleans TRUE/FALSE, strings quote-doubled.

##### 8.6 `mockApi.ts`
In-memory `jobs` Map and `loads` Map; `STAGES` per mode (fast 6 stages, scenario 8, testcase 7 — labels in code, e.g. fast: handoff "Record generation-job handoff"(Boomi), schema "Validate normalized schema", graph "Build dependency graph (parents first)", rows "Generate parent then child records", validate "Run nine validation checks", store "Store dataset for paginated preview"; scenario adds ai "AI builds the generation blueprint", bp "Validate blueprint against schema (Pydantic)", scenarios "Apply scenario rules and verify counts"; testcase: ai "AI proposes test-case plan", spec, prereq "Generate prerequisite records, parents first", manifest "Build test-case manifest").
- `listTargets` 150 ms -> approved list. `testConnection` 900 ms: `matchTarget` (by `targetId`; mongo URI regex; or exact host/port/database match) else fail "Destination is not on the approved network policy. Use a registered test connection."; type mismatch -> "The registered target is a different database type."; non-mongo without password and without targetId -> "Authentication failed for the supplied user. Check the username and password."; success `{ok, metadataAccess:'Allowed', tablesDiscovered, targetId, message}`. NOTE: because manual hosts are `*.atom.internal`, demo users effectively use "Saved connections".
- `fetchSchema` 1800 ms. `parseCollection` throws "Reading a Postman collection needs the backend. Set VITE_API_BASE to the FastAPI origin." (so Mode 3 with an uploaded spec cannot complete in mock mode). `planBlueprint` 500 ms.
- `createJob`: id `job_{seq 4-digit}{4 random chars}`; runs `run(c)` asynchronously; each stage sleeps 350-700 ms; stage `ai` (scenario) builds blueprint, `bp` detail "N scenario(s), M table count(s) accepted"; `rows` runs `generateTables`; `prereq` runs `generateTestCases`; `scenarios` computes coverage; `validate` builds report (unsupported constraints merged). `generateTables`: seeds GenContext (`blueprint.localeHint ?? config.locale`, seed, domain), requested counts, auto-adds required parents with 5 rows (adjustment text `Added parent table "{p}" with 5 records because a selected table has a required foreign key to it.`), reports cyclic/self-ref tables in unsupported list, feasibility trimming for unique enum columns / unique 1:1 FKs (adjustments "…records impossible, unique column … Proposed N." / "…unique foreign key … needs N distinct … Proposed M."), scenario slot allocation (shuffled slots forced to scenario values, remaining rows get another enum value), self-reference first row null. `buildReport`: status failed if any failed check, partial if any warning or adjustments, else completed; percentages = (checked-failed)/checked rounded to 0.1; `testCoverage` for mode 3 (`needingRules = needsRules && !ready`). `getJob` returns a JSON clone. `getPreview` paginates rows and returns `links` (test ids by row index) from prerequisite linkage.
- `generateMissing` 700 ms: adds rows with scenario value for Missing/Partial scenarios (skipping tables whose parents have no rows), recomputes coverage, strips adjustments starting with "Scenario", rebuilds report.
- `exportFile` 300 ms -> `buildExport`. Load: `getLoadPlan` (parents-first, tables with rows) & `startLoad` (requires `loadAllowed`, else "Direct load is only enabled for the PostgreSQL test schema in the MVP."), load id `load_{6 random}`; 8 steps (confirm React done, job FastAPI, recv Boomi, batch Boomi, adapter Boomi, insert Database, status Boomi, verify FastAPI); `getLoad` derives progress purely from elapsed time: steps advance at 0/600/1200/1800 ms, inserts start at 2400 ms, 900 ms per table, +600 ms status, +900 ms verify; per-table `inserted` ramps linearly; final `boomiStatus` COMPLETE / ERROR, `status` success only if counts match and fk check has 0 failures; interim `EXECUTING` / `COMPLETE (verifying)`.
- Errors: unknown job -> "Job not found. Generated datasets live in server memory and may have expired. Please generate again."

---------------------------------------------------------------------------
#### 9. Build / deploy / run
- Local: `npm install`; `npm run dev` (http://localhost:5173); `npm run build` (`tsc -b && vite build` -> `dist/`); `npm run preview`; `npm run lint` (oxlint). Mock mode by default (no env). For real backend: create `.env.local` with `VITE_API_BASE=http://localhost:8000` (or HTTPS origin).
- Vercel: static SPA (framework Vite), rewrites everything to `/index.html`, env var `VITE_API_BASE` must be added in project settings (build-time). Backend needs CORS for `Authorization`, `Content-Type`, `X-Client-Id` headers, expose `Content-Disposition`.
- Security statements in README/UI: passwords/URIs used only for the connection test and cleared afterwards; schema and load requests carry only a target id. Basic credentials kept in sessionStorage only.

---

## Prompt 2 - Backend (Python FastAPI, Render)

> Copy everything from here to the end of this section into Claude.

You are a senior backend engineer. Build the complete **ATOM DATA FOUNDRY API** described below with Python 3.12 and FastAPI: schema discovery for PostgreSQL and MySQL, a generic constraint-aware data generation and repair engine, three modes (Fast Test, AI Realistic & Scenario, AI Test Case Generator from a Postman or OpenAPI file), nine validation checks, exports, an approved-load pipeline, an encrypted connection registry with audit, common HTTP Basic authentication, and the `/internal/*` API that Boomi calls.

Rules:
- Follow the specification below exactly: file tree, environment variables, models, routes, status codes, algorithms and tests. The engine must work for **any** schema from discovered metadata only: no schema-specific code, no hard-coded table or column names.
- Credentials are encrypted at rest and never returned to a client; the AI service receives only schema and prompts; every route except `/health` requires HTTP Basic, and the API refuses to serve when credentials are unset.
- Work in this order: config and models, registry and auth, metadata (SQL, normalise), engine (generator, repair, validator, planner, pipeline), AI, Mode 3 (apisource, tc_planner, tc_validate, samples), exporters, jobs and store, loader, routers, scripts, tests, Render config and README.
- Write the tests as you go; the fuzz test over randomly generated schemas must show zero failed checks and a successful load.

Improvements to apply while rebuilding:
1. Scope jobs, previews, exports and loads to the requesting `X-Client-Id` (return 404 for others).
2. Use the saved `ssl` mode when loading and verifying; re-check the destination policy when a job or load starts, not only at connection test time.
3. Validate `/api/plan` and `/api/collection/parse` bodies with Pydantic models (400/422 instead of 500).
4. If Boomi is configured but fails, return a clear error that says Boomi failed (and keep the optional direct-mode fallback behind a flag); make Boomi's `handoff` stage honest in the stage list.
5. Remove dead items (the `pandas` dependency, unused settings and fields), use a FastAPI lifespan handler instead of `on_event`, correct the README (OpenAI and HTTP Basic, not Gemini or an internal secret), and fix the `.gitignore` entry for the Aiven CA file.
6. Keep Mode 3 results advisory: its checks never mark a job `failed`.

Acceptance checks (all must pass):
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m pytest -q
.venv/Scripts/python scripts/dev_demo.py   # API on :8000 with an embedded PostgreSQL demo database
curl http://localhost:8000/health
```
Then start `uvicorn app.main:app` with a real `.env`, call `/api/auth/check` with and without credentials (200 / 401), and run a Fast Test job and a load against a disposable PostgreSQL database.

### Specification (backend)

Source: `D:\ai_foundry\ai_foundry_backend` (all of `app/`, `scripts/`, `tests/`, requirements, render.yaml, targets.example.json, .env.example, README.md). Excluded by instruction: `.venv`, `__pycache__`, `data/`, `.pytest_cache`, `active-development/` (Boomi), `aiven-ca.pem`, `.env`. This document is written so the backend can be rebuilt without the code. Secrets are never reproduced.

---------------------------------------------------------------------------------------------------

#### 1. Purpose, architecture, call flow, modes

##### 1.1 Purpose
A service that (a) connects to a user's PostgreSQL / MySQL / MongoDB test database in a metadata-only way, (b) turns its discovered schema into a unified `Schema` model, (c) generates synthetic, constraint-valid, interconnected test data (or API test cases), (d) validates it with a fixed set of checks, (e) exports it in many formats, and (f) optionally loads it into a PostgreSQL test database after explicit approval.

JSON on the wire is camelCase (pydantic `alias_generator=to_camel`, `populate_by_name=True`) so the React app (`src/types.ts`, `src/api/httpApi.ts`) works unchanged.

##### 1.2 Components and call flow
```
React (Vercel)  --HTTP Basic + X-Client-Id-->  FastAPI /api/*          (routers/public.py)
FastAPI  --HTTP Basic (same creds)-->  Boomi Process A (metadata)  [POST {SERVER_BASE_URL}{BOOMI_METADATA_PATH}]
Boomi Process A  --HTTP Basic-->  FastAPI /internal/registry/lookup, /internal/metadata, /internal/audit
FastAPI  --HTTP Basic-->  Boomi Process B (load) [POST {SERVER_BASE_URL}{BOOMI_LOAD_PATH}]
Boomi Process B  --HTTP Basic-->  FastAPI /internal/batch, /internal/load/execute, /internal/audit
FastAPI /internal/*  -->  registry DB (MySQL, Fernet-encrypted creds)  and  user database (via SQLAlchemy / PyMongo)
```
* One credential pair (`API_USERNAME`/`API_PASSWORD`) protects EVERY route except `GET /health`; it is used by React, by Boomi calling FastAPI, and by FastAPI calling Boomi (unless `SERVER_AUTH_TYPE=bearer`).
* Requests to Boomi carry only a `targetId` (never credentials). Python decrypts the credentials from the registry when Boomi calls `/internal/metadata` or `/internal/load/execute`.
* **Metadata flow** (`metadata/service.discover_schema`): audit `metadata REQUESTED` -> if `boomi_client.configured()` call Process A, else call the Python adapter directly (direct mode) -> audit `COMPLETE` / `FAILED` -> normalize raw JSON into `Schema`. In direct mode a first warning "Development mode: Boomi is not configured, so metadata was read directly by the Python adapter." is inserted.
* **Load flow** (`loader.start_load`): create `LoadJob`, audit `load REQUESTED`, then a daemon thread either runs `_via_boomi` (Boomi Process B which calls back `/internal/batch` and `/internal/load/execute`) or `run_direct` (same steps in-process). Direct mode marks the Boomi steps with detail "Boomi not configured, executed directly by the Python adapter".
* Jobs run in a daemon `threading.Thread` per job; the UI polls `GET /api/jobs/{id}`.
* Persistence: in-memory dicts mirrored to JSON files in `DATA_DIR/jobs/` (jobs only; loads are memory only).

##### 1.3 Modes (`JobConfig.mode`: `fast` | `scenario` | `testcase`)
1. **Fast Test** (`fast`): rule/constraint-driven generation for user-supplied table counts. No AI. 6 stages.
2. **AI Realistic & Scenario** (`scenario`): builds a `Blueprint` (rule-based parse of the description, optionally merged with an OpenAI response) containing table counts, exact enum "scenario" counts (e.g. "30 APPROVED timesheets"), value pools for free-text columns, column rules; then generates, applies scenario slots, reports scenario coverage; "generate missing" endpoint can top up. 8 stages.
3. **AI Test Case Generator** (`testcase`, "Mode 3"): NO records are generated. Parses a user's Postman collection / OpenAPI file, matches endpoints to tables, optionally samples <=5 existing rows read-only, builds positive/negative/boundary/workflow test cases with request fixtures (rule-based + optional AI extras), validates them (advisory only), and exports Postman / Pytest / XLSX. Job status is never `failed` because of validation checks (only on exceptions). 8 stages.

---------------------------------------------------------------------------------------------------

#### 2. Dependencies, Python, environment

##### 2.1 `requirements.txt` (all unpinned lower bounds)
```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.7
sqlalchemy>=2.0
psycopg[binary]>=3.2
pymysql>=1.1
pymongo>=4.8
faker>=30
numpy>=2.0
pandas>=2.2          (declared; never imported anywhere in app/)
networkx>=3.3
openpyxl>=3.1
httpx>=0.27
pyyaml>=6.0
cryptography>=43
```
`requirements-dev.txt`: `-r requirements.txt`, `pytest>=8`, `pgserver>=0.1.4` (embedded PostgreSQL; tests and scripts also import `psycopg`, `uvicorn`).

Python: 3.12 (README "Python 3.12"; render.yaml `PYTHON_VERSION=3.12.3`). Code uses `from __future__ import annotations` everywhere.

DB drivers: PostgreSQL URL driver `postgresql+psycopg` (psycopg 3); MySQL `mysql+pymysql`; MongoDB via `pymongo.MongoClient`.

##### 2.2 Environment variables (`app/config.py`, `get_settings()` is `lru_cache`d; tests call `get_settings.cache_clear()`)
`.env` in the backend root is read by a tiny parser (`_load_dotenv`): skips blank lines/`#`/lines without `=`; splits on first `=`; strips whitespace and surrounding quotes; uses `os.environ.setdefault` (real environment wins; an already-set empty var also wins).

| Env var | Default | Meaning / Settings field |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | comma list -> `cors_origins` |
| `API_USERNAME` | `""` | HTTP Basic user (`api_username`). Empty => 503 on every protected call |
| `API_PASSWORD` | `""` | HTTP Basic password (`api_password`) |
| `TARGETS_FILE` | `<ROOT>/targets.json` | file-mode approved targets (`targets_file`) |
| `DATA_DIR` | `<ROOT>/data` | job JSON persistence dir (`data_dir`) |
| `REGISTRY_DB_URL` | none | full SQLAlchemy URL of registry DB; wins over MYSQL_* |
| `MYSQL_HOST` | none | if non-empty and no REGISTRY_DB_URL, builds `mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db}` |
| `MYSQL_USER` | `root` | |
| `MYSQL_PASSWORD` | `""` | |
| `MYSQL_PORT` | `3306` | |
| `MYSQL_DATABASE` | `atom_registry` | |
| `MYSQL_SSL_CA` | `""` | path to CA PEM for verified TLS (`registry_ssl_ca`) |
| `REGISTRY_ENCRYPTION_KEY` | `""` | Fernet key (`registry_key`) |
| `ALLOW_PRIVATE_TARGETS` | `false` | `.lower()=="true"` -> allow loopback/private destinations |
| `MAX_TARGETS_PER_OWNER` | `10` | `int()`; saved active connections per X-Client-Id |
| `BOOMI_ENABLED` | `false` | `.lower()=="true"`; false = direct mode |
| `SERVER_BASE_URL` | `""` | Boomi runtime base URL (trailing `/` stripped) |
| `SERVER_AUTH_TYPE` | `basic` | lowercased; `bearer` switches to bearer header |
| `SERVER_USERNAME` | falls back to `API_USERNAME` | |
| `SERVER_TOKEN` | falls back to `API_PASSWORD` | Basic password toward Boomi |
| `SERVER_BEARER_TOKEN` | `""` | used when auth type = bearer |
| `BOOMI_METADATA_PATH` | `/ws/simple/executeAfmetadata` | Process A listener path |
| `BOOMI_LOAD_PATH` | `/ws/simple/executeAfload` | Process B listener path |
| `SERVER_VERIFY_SSL` | `true` | `.lower()!="false"` -> httpx `verify` |
| `OPENAI_API_KEY` | `""` | empty => AI disabled (rules only) |
| `OPENAI_MODEL` | `gpt-4o` | |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | trailing `/` stripped |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | parsed into settings but never used by any code |

Other env: `MYSQL_ADMIN_URL` (read only by `scripts/registry_admin.py init`), `PGADMIN_URL`, `PG_PLACEMENT_USER` (default `atom_app`), `PG_PLACEMENT_PASSWORD` (seed script), per-target `usernameEnv`/`passwordEnv`/`uriEnv` names from `targets.json`, `PORT` (Render), `PYTHON_VERSION` (Render), `BASE_URL`/`AUTH_TOKEN` (generated pytest file), `FUZZ_MAX` (fuzz test, default 15), plus the dev-demo `DEMO_PG_USER/DEMO_PG_PASS`, test `T_PG_USER/T_PG_PASS`.

##### 2.3 `.env.example` (values blank for secrets)
Contains: `CORS_ORIGINS=http://localhost:5173`, `API_USERNAME=`, `API_PASSWORD=`, `PUBLIC_BASE_URL=http://localhost:8000`, `MYSQL_HOST=localhost`, `MYSQL_PORT=3306`, `MYSQL_USER=atom_registry_app`, `MYSQL_PASSWORD=`, `MYSQL_DATABASE=atom_registry`, `MYSQL_ADMIN_URL=`, `REGISTRY_ENCRYPTION_KEY=` (generate with `registry_admin.py genkey`), `BOOMI_ENABLED=false`, `SERVER_BASE_URL=`, `SERVER_AUTH_TYPE=basic`, `SERVER_USERNAME=`, `SERVER_TOKEN=`, `SERVER_BEARER_TOKEN=`, `SERVER_VERIFY_SSL=true`, `OPENAI_API_KEY=` ("leave key empty to use rule-based planners"), `OPENAI_MODEL=gpt-4o`. It omits MYSQL_SSL_CA, ALLOW_PRIVATE_TARGETS, MAX_TARGETS_PER_OWNER, REGISTRY_DB_URL, TARGETS_FILE, DATA_DIR, OPENAI_BASE_URL, BOOMI_*_PATH.

##### 2.4 `render.yaml`
One web service `atom-foundry-api`, `runtime: python`, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, `healthCheckPath: /health`. Env vars: `PYTHON_VERSION=3.12.3`; secret/unsynced (`sync: false`): `CORS_ORIGINS` (comment: your Vercel URL), `API_USERNAME`, `API_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_SSL_CA` (comment: paste Aiven CA path or mount as secret file), `REGISTRY_ENCRYPTION_KEY`, `OPENAI_API_KEY`; fixed: `OPENAI_MODEL=gpt-4o`, `BOOMI_ENABLED="false"`, `ALLOW_PRIVATE_TARGETS="false"`. Not listed: SERVER_* vars, MAX_TARGETS_PER_OWNER, DATA_DIR (so job files go to the ephemeral disk under the app folder; the store docstring says restarts "keep datasets", which holds only if the disk persists).

---------------------------------------------------------------------------------------------------

#### 3. File tree and responsibility

```
ai_foundry_backend/
  .env.example            template of env vars
  .gitignore              .venv/ __pycache__/ data/ .env targets.json .pytest_cache/ active-development/ .aiven-ca.pem
  README.md               run/layout/modes/auth notes (partly stale, see section 13)
  render.yaml             Render deployment
  requirements.txt / requirements-dev.txt
  targets.example.json    sample file-mode approved targets (3 entries)
  app/
    __init__.py           empty
    main.py               FastAPI app, CORS, startup registry init, global 500 handler, /health
    config.py             Settings from env/.env
    auth.py               HTTP Basic dependency `require_basic`
    models.py             all Pydantic models (camelCase)
    registry.py           SQLAlchemy Core tables registered_targets, boomi_audit; Fernet; audit helpers
    targets.py            `Target` dataclass; registry/file loading; owner scoping; match_target
    policy.py             destination (SSRF) policy for user-entered hosts
    store.py              in-memory + JSON-file job store; in-memory load store
    jobs.py               stage lists per mode, job thread runner, generate_missing
    loader.py             load into PostgreSQL: key re-allocation, batching, skip/cascade, verification, Boomi/direct orchestration
    ai.py                 OpenAI chat-completions wrapper, blueprint + extra test-case prompts, validation/merge
    boomi_client.py       httpx POSTs to Boomi Process A / B
    metadata/
      sql.py              PG_METADATA_SQL, MYSQL_METADATA_SQL (one row, one JSON text column)
      adapter.py          check_credentials, sql_metadata, mongo_metadata, TLS args
      normalize.py        raw metadata JSON -> Schema (SQL and Mongo)
      service.py          discover_schema (Boomi vs direct, audit)
    routers/
      public.py           /api/* (React)
      internal.py         /internal/* (Boomi callbacks)
    engine/
      generator.py        GenContext: value generation, keys, uniqueness, FKs, dates, add_row, create_chain; dependency_order; required_parents
      pipeline.py         JobState; generate_tables; restore_context; build_report; coverage; unsupported
      repair.py           post-generation self-healing pass
      validator.py        the nine checks, scenario coverage, unsupported-constraint list, `_type_ok`
      planner.py          rule_blueprint (description parsing)
      exporters.py        all export formats, Postman + Pytest generators
      apisource.py        Mode 3: Postman v2 / OpenAPI parser, secret masking, table matching
      tc_planner.py       Mode 3: Planner (cases), finalize, from_ai
      tc_validate.py      Mode 3: advisory checks, body_problems
      samples.py          Mode 3: read-only row sampling
  scripts/
    dev_demo.py           run API against throw-away embedded PostgreSQL
    embedded_pg.py        throw-away PostgreSQL as a "user database"
    registry_admin.py     CLI: genkey, init, add-target, list, deactivate
    seed_placement_db.py  create placement_test_db + app role on an existing server
    seed_placement_db.sql empty 8-table demo schema
  tests/
    __init__.py conftest.py test_e2e.py test_fuzz_schemas.py test_registry_and_ai.py test_testcase_mode.py test_user_connections.py
```

##### 3.1 `main.py`
* `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")`.
* `FastAPI(title="ATOM DATA FOUNDRY API", version="1.0.0")`.
* CORS: `allow_origins=settings.cors_origins`, `allow_methods=["GET","POST","DELETE","OPTIONS"]`, `allow_headers=["Authorization","Content-Type","X-Client-Id"]`, `expose_headers=["Content-Disposition"]`. (no credentials flag; no PUT/PATCH.)
* Routers `public.router` then `internal.router`.
* `@app.on_event("startup")`: if `registry.enabled()`: `registry.init_schema()`; on any exception logs `registry init failed: <ClassName>` and keeps the API up.
* `@app.exception_handler(Exception)`: logs, returns 500 `{"detail": "Internal error. Check the server log."}`.
* `GET /health` (no auth): `{"status":"ok","boomi":"configured"|"direct-mode","ai":"openai"|"rules-only"}`.

---------------------------------------------------------------------------------------------------

#### 4. Pydantic models (`app/models.py`)

All inherit `CamelModel` (`ConfigDict(alias_generator=to_camel, populate_by_name=True)`) unless noted. Type aliases: `DbType = Literal["postgresql","mysql","mongodb"]`; `GenMode = Literal["fast","scenario","testcase"]`; `TestCategory = Literal["positive","negative","boundary","workflow"]`; `Cell = Any`. Routes that use `response_model_by_alias=True` serialize camelCase.

**ConnectionRequest**: `db_type: DbType` (required); `target_id: str|None=None`; `host: str|None`; `port: int|None`; `database: str|None`; `username: str|None`; `password: str|None` (`Field(repr=False)`); `ssl: str|None`; `uri: str|None` (`repr=False`); `label: str|None`; `allow_load: bool=False`; `db_schema: str|None` with explicit **alias `"schema"`** (wire name `schema`, not `dbSchema`; `populate_by_name` also allows `db_schema`).

**ApprovedTarget**: `id`, `label`, `db_type`, `host`, `port:int`, `database`, `load_allowed: bool`, `schema_name: str|None=None` (wire `schemaName`).

**ConnectionResult**: `ok: bool`, `db_type`, `database: str`, `metadata_access: Literal["Allowed","Denied"]`, `tables_discovered: int`, `target_id: str|None=None`, `message: str`.

**Column**: `name`, `type: str`, `max_length:int|None`, `nullable: bool=False`, `primary_key: bool=False`, `unique: bool=False`, `default: str|None`, `enum_values: list[str]|None`, `check: str|None`, `missing: bool|None`, `precision:int|None` (numeric p), `generated: bool|None` (GENERATED ALWAYS AS (expr) STORED, never written), `identity_always: bool|None` (GENERATED ALWAYS AS IDENTITY; needs OVERRIDING SYSTEM VALUE), `scale:int|None`.

**ForeignKey**: `column`, `ref_table`, `ref_column`.

**Table**: `name`, `columns: list[Column]`, `foreign_keys: list[ForeignKey]=[]`, `unique_together: list[list[str]]=[]` (composite UNIQUE / composite PK / multi-column unique indexes), `needs_definition: bool|None` (Mongo collection without validator).

**Schema**: `db_type`, `database`, `schema_name: str|None`, `target_id: str|None`, `tables: list[Table]`, `warnings: list[str]=[]`, `source: Literal["boomi-jdbc","boomi-pymongo"]="boomi-jdbc"`, `extracted_at: str=""`; method `table(name)->Table|None`.

**Scenario**: `table`, `column`, `value: str`, `count: int` (`ge=0`). **TableCount**: `table`, `count: int ge=0`.

**TestCaseConfig**: `feature: str=""`; `categories: list[TestCategory]` (required); `collection_text: str|None` (Postman v2.x or OpenAPI/Swagger text); `open_api_text: str|None` (legacy alias of the same meaning); `use_db_samples: bool=False`; `api_base_url: str|None`; `selected_endpoints: list[str]|None` (endpoint keys `"METHOD /path"`); `business_rules: str|None`.

**JobConfig**: `mode: GenMode`; `tables: list[TableCount]=[]`; `locale: str="en_US"`; `seed: int|None`; `description: str|None`; `scenarios: list[Scenario]|None`; `test_case: TestCaseConfig|None` (wire `testCase`).

**ColumnRule**: `table`, `column`, `rule: str`. **ValuePool**: `table`, `column`, `values: list[str]`.

**Blueprint**: `domain: str` (required), `locale_hint: str="en_US"`, `table_counts: list[TableCount]=[]`, `scenarios: list[Scenario]=[]`, `column_rules: list[ColumnRule]=[]`, `value_pools: list[ValuePool]=[]`, `notes: list[str]=[]`.

**ValidationCheck**: `id`, `label`, `checked:int`, `failed:int`, `status: Literal["passed","warning","failed","skipped"]`, `detail: str|None`.

**ScenarioCoverage**: `scenario: Scenario`, `generated:int`, `result: Literal["Covered","Partial","Missing","Unsupported"]`, `note: str|None`.

**PrereqRecord**: `table`, `key`. **Fixture**: `method`, `path`, `body: dict[str,Any]|None`, `headers: dict[str,str]={}`, `expected_status: str|None` ("2xx","4xx" or exact code), `note: str|None` (`"capture-id:<pk>"` marks a create step whose id is captured).

**TestCase**: `id`, `category: TestCategory`, `title`, `table: str=""`, `preconditions: list[str]`, `steps: list[str]`, `expected: str`, `needs_rules: bool`, `prerequisite_records: list[PrereqRecord]=[]`, `fixture: Fixture|None`, `requests: list[Fixture]|None` (ordered chain; fixture = first request), `endpoint: str|None` ("POST /api/tasks"), `ready: bool`, `readiness_note: str`.

**TestCaseCoverage**: `by_category: dict[str,int]`, `total`, `with_prerequisites`, `ready_to_export`, `needing_rules`.

**PerTable**: `table`, `requested`, `generated`.

**Report**: `job_id`, `db_type`, `database`, `tables_discovered`, `mode`, `records_requested`, `records_generated`, `data_type_validity: float`, `relationship_integrity: float`, `uniqueness_violations:int`, `status: Literal["completed","partial","failed"]`, `duration_ms`, `unsupported_constraints: list[str]`, `adjustments: list[str]`, `checks: list[ValidationCheck]`, `per_table: list[PerTable]`, `scenario_coverage: list[ScenarioCoverage]|None`, `test_coverage: TestCaseCoverage|None`.

**Stage**: `id`, `label`, `layer: str`, `state: Literal["pending","running","done","failed"]="pending"`, `detail: str|None`.

**Job**: `id`, `config: JobConfig`, `status: Literal["running","completed","partial","failed"]="running"`, `stages: list[Stage]`, `blueprint: Blueprint|None`, `report: Report|None`, `test_cases: list[TestCase]|None`, `error: str|None`.

**PreviewPage**: `table`, `total`, `page`, `page_size`, `columns: list[str]`, `rows: list[dict]`, `links: dict[int,list[str]]|None`.

**LoadTable**: `table`, `expected`. **LoadPlan**: `target: ApprovedTarget`, `tables: list[LoadTable]`. **LoadStep**: `id`, `layer`, `label`, `state` (same literal as Stage), `detail`. **LoadTableResult**: `table`, `expected`, `inserted=0`, `failed_batches=0`, `skipped=0`. **Verification**: `counts_match=False`, `fk_valid=False`. **LoadJob**: `id`, `status: Literal["running","success","failed"]="running"`, `steps: list[LoadStep]`, `per_table: list[LoadTableResult]`, `boomi_status: str="RECEIVED"`, `warnings: list[str]=[]`, `verification: Verification=Verification()`, `error: str|None`.

Request-only models defined in routers: `SchemaRequest(target_id)`, `TargetBody(target_id, approved: bool=False)` (public); `MetaReq(target_id)`, `BatchReq(job_id, load_id: str="")`, `ExecReq(load_id, job_id, target_id)`, `LookupReq(target_id)`, `AuditReq(request_id, process_name, status, target_id: str="", message: str="")` (internal). `/api/plan`, `/api/collection/parse` and `/api/jobs` take a raw `dict` body.

---------------------------------------------------------------------------------------------------

#### 5. HTTP routes

##### 5.1 Auth (`auth.require_basic`), applied as router-level dependency on both routers
1. If `API_USERNAME` or `API_PASSWORD` empty -> **503** `"API credentials are not configured on the server (set API_USERNAME and API_PASSWORD)."` (fail closed).
2. `Authorization` header partitioned by first space; scheme must be `basic` (case-insensitive) and token non-empty else **401** `"Authentication required."`.
3. Token `base64.b64decode(validate=True)` then utf-8 decode then `partition(":")`; binascii/Unicode error -> **401** `"Invalid credentials."`.
4. `hmac.compare_digest` on UTF-8 bytes for user and password (both always evaluated); mismatch -> **401** `"Invalid credentials."`.
5. `WWW-Authenticate: Basic realm="atom-foundry", charset="UTF-8"` header is attached to 401s only when `request.url.path` starts with `/internal` (so browsers do not pop a dialog for `/api`). Returns the username.

##### 5.2 Ownership: `client_id` dependency (public router, type `Owner`)
* Reads header `X-Client-Id` (default `""`).
* If registry is NOT enabled -> returns `None` (header ignored; file mode).
* Else must match `^[A-Za-z0-9_-]{8,64}$` else **400** `"Missing or invalid X-Client-Id header."`.
* The id is the anonymous per-browser owner of saved connections; `get_target(id, owner)` / `registry.list_rows(owner=...)` scope all reads, so another owner's target is "not found" (404/403 messages below). Jobs and loads are NOT owner-scoped (any authenticated caller who knows a job id can read it).

##### 5.3 Public routes (`APIRouter(prefix="/api", dependencies=[Depends(require_basic)])`)

| Route | Details |
|---|---|
| `GET /api/auth/check` | returns `{"ok": true}` (auth already enforced). |
| `GET /api/targets` | `[ApprovedTarget camelCase]` for `load_targets(owner).values()` (registry: only owner's active rows; file: all). No secrets. |
| `DELETE /api/targets/{target_id}` | registry disabled -> **405** `"Saved connections are managed by the administrator in this mode."`; `registry.deactivate(id, owner)` false -> **404** `"Saved connection not found."`; else `{"deleted": id}`. Soft delete (`active=false`). |
| `POST /api/connections/test` | body `ConnectionRequest`; response `ConnectionResult` (camelCase). ALWAYS HTTP 200; failures are `ok:false, metadataAccess:"Denied", tablesDiscovered:0` with a `message`. See 5.4. |
| `POST /api/schema` | body `{targetId}`; target not found for owner -> **404** `"Saved connection not found."`; `discover_schema` failure -> **502** `"Schema extraction failed: <friendly>"`; returns `Schema` (by alias). |
| `POST /api/plan` | body `{"schema":Schema,"config":JobConfig}` (raw dict, KeyError -> 500 if keys missing); returns `Blueprint` from `ai.plan_blueprint` (source discarded). |
| `POST /api/collection/parse` | body `{"text":..., "schema"?:Schema}`; `len(text) > 8_000_000` -> **413** `"The file is larger than 8 MB."`; `ValueError` -> **422** with message; other exception -> **422** `"Could not read the file: <ExceptionName>"`. Returns `{"kind","title","baseUrl","endpoints":[{"id": key, "method","path","name","folder","table","hasBody": body is not None}]}`; `table` filled only if `schema` was supplied (via `match_tables`). |
| `POST /api/jobs` | body `{"schema","config"}`; validation error -> **422** `"Invalid job request: <pydantic error>"`; `schema.targetId` set but not accessible to owner -> **403** `"Saved connection not found."`; returns `{"jobId": "job_<10 hex>"}` and starts the thread. |
| `GET /api/jobs/{job_id}` | `Job` by alias; missing -> **404** `"Job not found. Generated datasets may have expired. Please generate again."` |
| `GET /api/jobs/{job_id}/preview?table=&page=0&page_size=20` | `page>=0`, `1<=page_size<=100` (422 otherwise). No rows for table -> **404** `"No generated data for table <t>."`. Returns `PreviewPage` with `columns` from the schema table (or keys of first row), `rows` slice, `total`, and `links` = for tables with `st.links` entries, `{rowIndexInPage: [strings]}` keyed by `str(row[pk])` (`links` is always empty in current code since nothing populates `JobState.links`; omitted -> `null`). |
| `POST /api/jobs/{job_id}/generate-missing` | job not finished (no report) -> **409** `"Job has not finished."`; runs `jobs.generate_missing` synchronously; returns `Job`. |
| `GET /api/jobs/{job_id}/export?format=` | unknown format -> **400** `"Unknown export format: <f>"`; no report or status `failed` -> **409** `"Export is disabled until validation passes."`; `postman` and `not st.has_spec` -> **409** `"A Postman collection needs an OpenAPI specification."`; returns bytes with `Content-Disposition: attachment; filename="..."` plus `Access-Control-Expose-Headers: Content-Disposition`. |
| `POST /api/jobs/{job_id}/load-plan` | body `TargetBody`; target not found for owner -> 404 `"Saved connection not found."`; returns `LoadPlan{target: public(), tables:[{table, expected: len(rows)}]}` for `st.order` tables that have rows. |
| `POST /api/jobs/{job_id}/load` | order of checks: job exists (404) -> `approved` false -> **400** `"Nothing loads without explicit approval."` -> target not found for owner **404** `"Saved connection not found."` -> `not t.load_allowed` **403** `"Loading is not enabled for this connection. Reconnect and tick 'allow loading' (PostgreSQL test databases only)."` -> `schema.targetId` set and != target id **403** `"Data was generated for a different connection."` -> no report or status failed **409** `"Load is disabled until validation passes."`. Then `load_id="load_<8 hex>"`, `loader.start_load(...)`; returns `{"loadId": ...}`. |
| `GET /api/loads/{load_id}` | `LoadJob` by alias; missing -> **404** `"Load job not found."` |

##### 5.4 `POST /api/connections/test` logic
Local helper `deny(msg, database="")`. Three branches:
1. **`targetId` supplied** (any mode): `get_target(target_id, owner)`; none -> deny `"Unknown saved connection."`. No credentials needed.
2. **Registry enabled (user-entered connection)**:
   * MongoDB: `_parse_mongo(uri)` accepts schemes `mongodb`/`mongodb+srv` with hostname; returns (host, port or 27017, database from path stripped of `?...`, srv flag). Fail -> `"Enter a valid MongoDB connection URI (mongodb:// or mongodb+srv://)."`; no database -> `"Include the database name in the MongoDB URI (mongodb://host/database)."`. username/password empty, uri = request uri.
   * SQL: host/database stripped; requires host, port, database, username else `"Host, port, database and username are required."`.
   * `policy.check_destination(host, port, srv)` reason -> deny.
   * PostgreSQL schema: `(db_schema or "public").strip()` must match `^[A-Za-z_][A-Za-z0-9_$]{0,62}$` else `"The schema name may only contain letters, digits, _ and $ (max 63 characters)."`.
   * Build probe `Target` (ssl default `"prefer"`, port `port or 27017`) and call `adapter.check_credentials(probe, username, password)`; exception -> deny `_connect_error(e)` (with database).
   * `registry.find_existing(owner, db_type, host, port, database, username, pg_schema)` (match on schema via `COALESCE(schema_name,'')`); if none and `count_for_owner(owner) >= MAX_TARGETS_PER_OWNER` -> deny `"You can save up to {N} connections. Remove one first."`. `tid = existing or f"t_{token_hex(6)}"`.
   * `registry.upsert_target(tid, (label or f"{database} ({host})")[:160], ..., load_allowed=bool(allow_load and db_type=="postgresql"), owner, schema=pg_schema)`; `created = None if existing else tid`; `target = get_target(tid, owner)`. (Saving happens BEFORE metadata discovery; on discovery failure a newly created target is deactivated.)
3. **File mode** (no registry): host/port/db (for mongo from URI); `match_target(db_type, host, port, db)` must equal an approved target exactly else deny `"Destination is not on the approved network policy. Use a registered test connection."`; non-mongo requires username AND password else `"Authentication failed for the supplied user. Check the username and password."`; `check_credentials(target, username, password)` failure -> same auth message.

Then: `target.db_type != req.db_type` -> `"The saved connection is a different database type."`. `discover_schema(target)`; exception -> (deactivate created) deny `"Could not read metadata: <_friendly(e)>"`. Success -> `ConnectionResult(ok=True, ..., tablesDiscovered=len(tables), targetId, message="Connection successful. Metadata-only access confirmed." + hint)` where hint (PostgreSQL with zero tables) is ` No tables were found in schema "<s>". Check the schema name.`

Helpers: `_detail(e)` = first line of error, `(Background on this error...)` removed, whitespace collapsed, truncated 220. `_connect_error(e)` lower-cases class name + message and maps in order: auth failures ("password authentication failed", "authentication failed", "access denied", or "authentication" without "ssl") -> `"Authentication failed for the supplied user. Check the username and password."`; "channel binding" -> `'The server and client could not agree on channel binding. Try SSL mode "require".'`; "does not exist"/"unknown database" -> `"The database name was not found on that server."`; timeout / could not connect / refused / serverselection / can't connect / name or service not known / getaddrinfo -> `"Could not reach the database. Check the host, port and firewall, and that it accepts connections from this server."`; "ssl"/"tls"/"certificate" -> `"The secure (TLS/SSL) connection could not be established. Check the SSL setting."`; else `"Could not connect with the supplied details."`; all append ` Driver said: <detail>` when a detail exists (driver messages assumed password-free). `_friendly(e)` returns first line truncated to 200 but if it contains `password`, `postgresql://`, `mongodb://` or `mysql+` returns `"the database or integration service refused the request."`.

##### 5.5 Internal routes (`prefix="/internal"`, same Basic auth, challenge header on 401)

| Route | Body | Behaviour |
|---|---|---|
| `POST /internal/metadata` | `{targetId}` | `get_target(id)` (no owner filter; any active target) none -> **404** `"Unknown or inactive target."`; returns raw metadata dict: `adapter.mongo_metadata(t)` for mongodb else `adapter.sql_metadata(t)`; exception -> **502** `"Metadata read failed: <ExceptionName>"`. (Process A: Boomi never sees credentials.) |
| `POST /internal/batch` | `{jobId, loadId=""}` | unknown job -> **404** `"Unknown job."`; if load exists marks steps `recv` done, `batch` done with detail `Batch <jobId> located`, `adapter` running. Returns `{"batchRef": jobId, "tables":[{"table","rows"}] }` in load order for non-empty tables (no row data). |
| `POST /internal/load/execute` | `{loadId, jobId, targetId}` | unknown load -> **404** `"Unknown load."`; sets `adapter` done ("Python database adapter selected"); `loader.run_adapter`; `PermissionError` -> **403** with message; other exception -> `loader.fail(load, msg)` and returns 200 `{"status":"ERROR","perTable":[],"error": msg[:300]}`; success returns `{"status": res["status"] ("COMPLETE"/"ERROR"), "perTable": [...], "error": load.error}`. |
| `POST /internal/registry/lookup` | `{targetId}` | returns `{"found": 1|0, "db_type": str, "load_allowed": 1|0}` (snake_case keys, ints) for Boomi's gate. |
| `POST /internal/audit` | `{requestId, processName, status, targetId="", message=""}` | if registry enabled writes `registry.audit(..., source="boomi")`; returns `{"recorded": registry.enabled()}`. |

Note: the `boomi_client` docstring says Boomi calls `/internal/jobs/{job}/batch`; the real path is `/internal/batch`. `adapter.py` docstring refers to `/internal/mongo/metadata`; the real route is `/internal/metadata` for both SQL and Mongo.

##### 5.6 `boomi_client.py`
* `BoomiError(RuntimeError)`; `configured()` = `boomi_enabled and bool(boomi_base_url)`.
* `_post(path, body, timeout)`: `auth=(boomi_username, boomi_token)` unless `SERVER_AUTH_TYPE=="bearer"` (or username empty -> no auth); bearer: header `Authorization: Bearer <SERVER_BEARER_TOKEN>` if token set. `httpx.post(base+path, json=body, auth, headers, timeout, verify=boomi_verify_ssl)`. `httpx.HTTPError` -> `BoomiError("Boomi is unreachable: ...")`; status >= 400 -> `BoomiError("Boomi returned HTTP <code>: <first 300 chars of body>")`; non-JSON -> `BoomiError("Boomi returned a non-JSON response")`.
* `run_metadata_process(target_id, db_type, request_id=None)`: POST `BOOMI_METADATA_PATH` body `{"requestId": request_id or uuid4().hex[:12], "targetId", "dbType"}`, timeout 90 s. Returns raw metadata JSON (`{"tables":[...]}` or `{"collections":[...]}`).
* `run_load_process(load_id, job_id, target_id)`: POST `BOOMI_LOAD_PATH` body `{"loadId","jobId","targetId"}`, timeout 600 s. Response is expected to carry `status` (`COMPLETE`/`SUCCESS` OK) and optionally `error`.
* **Fallback to direct mode**: there is NO runtime fallback on Boomi failure. Direct mode is chosen purely by `configured()`; if Boomi is configured and fails, metadata discovery raises (route returns 502 / `Could not read metadata`), and a load fails with the Boomi error.

---------------------------------------------------------------------------------------------------

#### 6. Registry, targets, policy, store

##### 6.1 Registry DB (`registry.py`), SQLAlchemy Core, MySQL in production, SQLite in tests
`enabled()` = `bool(registry_url)`. `engine()` is `lru_cache`d: `create_engine(url, pool_pre_ping=True, pool_recycle=1800, connect_args=args)`; for `mysql*` URLs `connect_timeout=15` and, if `MYSQL_SSL_CA` set, `ssl={"ca": <path>}` (verified TLS with CA file + hostname check; Aiven-style). `reset_cache()` clears the engine cache.

**Table `registered_targets`**: `id String(64) PK`; `owner String(64) NOT NULL default "shared" indexed`; `label String(160) NN`; `db_type String(16) NN`; `host String(255) NN`; `port Integer NN`; `database_name String(128) NN`; `schema_name String(128) NULL`; `username String(128) NN default ""`; `password_enc Text NN default ""`; `uri_enc Text NULL`; `ssl_mode String(16) NN default "prefer"`; `load_allowed Boolean NN default False`; `active Boolean NN default True`; `updated_at DateTime NN default utcnow (naive)`.

**Table `boomi_audit`**: `id BigInteger (variant Integer on sqlite) PK autoincrement`; `request_id String(64) NN`; `source String(16) NN` ('boomi'|'python'); `process_name String(64) NN`; `target_id String(64) NULL`; `status String(24) NN`; `message Text NULL`; `created_at DateTime NN default utcnow naive`.

**Migrations**: `init_schema()` = `metadata.create_all(engine())` then inspects `registered_targets` columns and, if `schema_name` is missing, executes `ALTER TABLE registered_targets ADD COLUMN schema_name VARCHAR(128) NULL`. Called at app startup and by `registry_admin.py init`. No other migrations framework.

**Encryption**: Fernet with `REGISTRY_ENCRYPTION_KEY`; `encrypt("")` -> `""`; `decrypt(None/"")` -> `""`; missing key -> `RuntimeError("REGISTRY_ENCRYPTION_KEY is not set. Generate one with: python scripts/registry_admin.py genkey")`; `InvalidToken` -> `RuntimeError("Cannot decrypt a registry credential: wrong REGISTRY_ENCRYPTION_KEY")`. Password and Mongo URI are encrypted (`password_enc`, `uri_enc`); username is stored in clear. Boomi is documented as reading only the non-secret columns.

**Functions**: `list_rows(active_only=True, owner=None)` (ordered by id; owner filter only if not None); `upsert_target(id, label, db_type, host, port, database, username="", password="", uri="", ssl_mode="prefer", load_allowed=False, owner="shared", schema="")` (select-then-update/insert in one transaction; `schema_name = schema or None`; always sets `active=True`); `deactivate(id, owner=None)` returns rowcount>0; `find_existing(owner, db_type, host, port, database, username, schema="")` among ACTIVE rows; `count_for_owner(owner)` = active count; `audit(request_id, process_name, status, message="", target_id=None, source="python")` best-effort (no-op if disabled; truncates request_id 64, source 16, process 64, status 24, message 2000; swallows exceptions logging `audit write failed: <Class>`); `recent_audit(request_id)` ordered by id; `purge_audit()` deletes all (unused by app).

**Audit events written by Python**: `metadata REQUESTED` ("via Boomi Process A"/"direct Python adapter"), `metadata COMPLETE`, `metadata FAILED` (message = exception class name), `load REQUESTED` ("job X, via Boomi Process B"/"direct Python adapter"), `load SUCCESS`/`FAILED` ("job X: counts_match=.. fk_valid=.."). Boomi writes via `/internal/audit` with `source="boomi"`.

##### 6.2 `targets.py`
`@dataclass Target`: `id, label, db_type, host, port, database, load_allowed, username="", password="", uri="", ssl="prefer", owner="shared", schema="public"`.
* `public()` -> `ApprovedTarget` (no secrets; `schema_name` only for postgresql).
* `sqlalchemy_url(username=None, password=None)`: `{postgresql+psycopg|mysql+pymysql}://quote_plus(user):quote_plus(pw)@host:port/database` (override creds for credential checks).
* `mongo_uri()`: stored `uri` if present, else `mongodb://[user:pw@]host:port/database`.
* `_from_registry(owner)`: each active row -> Target with `password=registry.decrypt(password_enc)`, `uri=registry.decrypt(uri_enc)`, `ssl=ssl_mode or "prefer"`, `schema=schema_name or "public"`, `port=int`.
* `_from_file()`: `targets_file` JSON list; entries use camelCase keys `id,label,dbType,host,port,database,loadAllowed(default false),usernameEnv,passwordEnv,uriEnv,ssl(default "prefer"),schema(default "public")`; username/password/uri are read from the NAMED environment variables (missing -> `""`). Missing file -> `{}`. `targets.example.json` ships three: `pg-placement-test` (postgresql, localhost:5432, placement_test_db, loadAllowed true, ssl prefer, env `PG_PLACEMENT_USER/PG_PLACEMENT_PASSWORD`), `mysql-retail-test` (mysql 3306 retail_test_db, loadAllowed false), `mongo-support-test` (mongodb 27017 support_test_db, loadAllowed false).
* `load_targets(owner=None)`: registry if enabled else file. `owner=None` returns all (trusted internal callers). `get_target(id, owner=None)`. `match_target(db_type, host, port, database)` exact match against `load_targets()` (file-mode policy for manual entries).
* NOTE: every `get_target`/`load_targets` call decrypts every row (O(n) per call).

##### 6.3 `policy.check_destination(host, port, srv=False) -> reason|None`
1. host lowercased/stripped. Empty host, or (not srv and no port), or port outside 1..65535 -> `"Enter a valid host and port."`.
2. Host longer than 253 or containing any of ` /\@#?` -> `"The host name contains characters that are not allowed."`.
3. Host in `{"metadata.google.internal","metadata","instance-data"}` -> `"Destination is not allowed by the network policy."`.
4. `srv` (mongodb+srv) -> allowed (no A record to inspect).
5. `socket.getaddrinfo(host, port, SOCK_STREAM)`; `gaierror` -> `"The host name could not be resolved."`.
6. For each resolved IP: link-local, unspecified, multicast or reserved -> `"Destination is not allowed by the network policy."` (always); private or loopback and not `ALLOW_PRIVATE_TARGETS` -> `"Private and local network addresses are not allowed. Use a database reachable from the internet."`.
Checked only at connection-test time (no re-check at schema/load time).

##### 6.4 `store.py`
* `_jobs: dict[str, JobState]`, `_loads: dict[str, LoadJob]`, `RLock`. `_dir(kind)` = `DATA_DIR/kind` (created).
* `put_job`, `save_job(st)` writes `DATA_DIR/jobs/<id>.json` with `{"job","schema"` (both `model_dump(by_alias=True, mode="json")`), `"dataset","order","links","coverage"` (list or null), `"adjustments","unsupported","requested","apiBaseUrl","hasSpec","aiSource"}` via `json.dumps(..., default=str)`. NOT persisted: `tc_checks`, `ctx`, `started`, `batch_ref`.
* `get_job(id)`: memory first, else file `<id>.json` if it exists and `id.replace("_","").isalnum()` (existence checked first, then name sanity), rebuilds `JobState`, caches it. `put_load`, `get_load` (memory only; loads vanish on restart), `lock()`.

---------------------------------------------------------------------------------------------------

#### 7. Metadata

##### 7.1 PostgreSQL SQL (`PG_METADATA_SQL`, bound param `:schema`, run inside `SET TRANSACTION READ ONLY`)
Returns ONE row, ONE text column `metadata` = `json_build_object('tables', COALESCE(json_agg(t ORDER BY t.name),'[]'::json))::text`. Per table in `pg_class c JOIN pg_namespace n` where `n.nspname = :schema AND c.relkind IN ('r','p')` (ordinary and partitioned tables) produces `{name, columns, constraints, uniqueIndexes}`:
* **columns** (ordered by attnum; `attnum>0 AND NOT attisdropped`): `name` (attname), `type` = `format_type(atttypid, atttypmod)` (e.g. `character varying(50)`, `numeric(8,2)`, `integer[]`), `udt` = `pg_type.typname`, `typeKind` = `pg_type.typtype` ('e' enum, 'b' base, ...), `maxLength` = `atttypmod - 4` only when `atttypmod > 0 AND typname IN ('varchar','bpchar')`, `nullable` = `NOT attnotnull`, `default` = `pg_get_expr(adbin, adrelid)` from `pg_attrdef`, `identity` = `attidentity <> ''`, `identityKind` = `attidentity` ('a' always / 'd' by default), `generated` = `attgenerated <> ''`, `enumValues` = labels from `pg_enum` ordered by `enumsortorder` where `enumtypid = atttypid`.
* **constraints** (`pg_constraint`, `contype IN ('p','u','f','c')`): `type` (contype), `name`, `columns` (attnames ordered by `conkey` ordinality), `refTable` (referenced relname), `refSchema` (referenced namespace), `refColumns` (ordered by `confkey`), `definition` = `pg_get_constraintdef` for `contype='c'` only.
* **uniqueIndexes**: from `pg_index i` where `indisunique AND NOT indisprimary AND NOT EXISTS (constraint with conindid = this index and contype in ('u','p'))` (i.e. indexes with no constraint object): `name`, `columns` (attnames from `indkey` where attnum > 0), `hasExpression` (any `indkey` entry = 0), `expression` = `pg_get_expr(indexprs, indrelid)`, `partial` = `indpred IS NOT NULL`.

##### 7.2 MySQL SQL (`MYSQL_METADATA_SQL`, no params)
One row/one column `metadata` = `JSON_OBJECT('tables', COALESCE(JSON_ARRAYAGG(JSON_OBJECT(...)), JSON_ARRAY()))` over `information_schema.TABLES` where `TABLE_SCHEMA = DATABASE() AND TABLE_TYPE='BASE TABLE'`. Per table `{name, columns, constraints}`:
* columns from `information_schema.COLUMNS`: `name`, `type` = `COLUMN_TYPE` (e.g. `varchar(50)`, `tinyint(1)`, `enum('a','b')`), `udt` = `DATA_TYPE`, `maxLength` = `CHARACTER_MAXIMUM_LENGTH`, `nullable` = `IS_NULLABLE='YES'`, `default` = `COLUMN_DEFAULT`, `identity` = `EXTRA LIKE '%auto_increment%'`. (No ordering clause, no `typeKind`, no `generated`, no CHECK or unique-index information.)
* constraints from `TABLE_CONSTRAINTS` for PRIMARY KEY/UNIQUE/FOREIGN KEY mapped to `'p'/'u'/'f'`, with `columns` (KEY_COLUMN_USAGE), `refTable` (`MAX(REFERENCED_TABLE_NAME)`), `refColumns`. No `refSchema`.

##### 7.3 Adapter (`metadata/adapter.py`)
* `check_credentials(t, username, password)`: mongodb: `MongoClient(t.mongo_uri(), serverSelectionTimeoutMS=8000)` + `admin.command("ping")`, closes client. SQL: `create_engine(t.sqlalchemy_url(username, password), connect_args=_connect_args(t), pool_pre_ping=False)`; `SELECT 1`; disposes.
* `_connect_args(t)`: PostgreSQL `{"connect_timeout": 8, "sslmode": t.ssl}` (the `{"verify-full":"verify-full"}.get` mapping is an identity no-op). MySQL `{"connect_timeout": 8}` plus `ssl = ssl.create_default_context()` unless `t.ssl == "disable"` (verified against the system CA store).
* `sql_metadata(t)`: engine from `t.sqlalchemy_url()`; PostgreSQL executes `SET TRANSACTION READ ONLY` then the SQL with `{"schema": t.schema}`; MySQL runs its SQL; `scalar_one()`; `json.loads` if str. Disposes engine.
* `mongo_metadata(t)`: `MongoClient(uri, serverSelectionTimeoutMS=6000)`; `db.list_collections()`; skips non-`collection` types (views); returns `{"collections":[{"name","validator": options.validator or None}]}`. Only metadata, never documents.

##### 7.4 `normalize_sql_metadata(raw, db_type, database, target_id, source="boomi-jdbc", schema_name=None) -> Schema`
Per table, per column (`_base_type(raw_type, udt, typeKind)` returns `(base, max_len)`), rules in this order:
1. Lower-case raw type. `*[]` -> `array:<inner base>`. startswith `json` -> `json`. `inet`/`cidr` -> `inet`. startswith `interval` -> `interval`. `bytea` -> `bytea`.
2. Regex `(character varying|varchar|character|char)\((\d+)\)` -> `varchar` with max_len. `typeKind == "e"` (PG enum type) -> `varchar`. startswith `timestamp` -> `timestamp` (covers timestamptz). startswith `time` -> `time`. startswith `numeric`/`decimal` -> `numeric`.
3. `t in {integer,int4,int,int(11)}` or startswith `int` (interval was already handled above) -> `integer`. `boolean` or `tinyint(1)` -> `boolean`. `text/character varying/character/json/jsonb/uuid` -> `uuid` if uuid else `text`. startswith `enum(` -> `varchar`. `double precision`/`real` or startswith `double`/`float` -> `numeric`. startswith `varchar` -> `varchar`. `date` -> `date`, `datetime` -> `timestamp`. Finally if `udt` in the integer set {integer,int,int4,int8,bigint,smallint,int2,serial,bigserial,tinyint,mediumint} -> `integer` (this is how `bigint` and `smallint` are mapped, since neither starts with "int"; any other unknown type falls through unchanged as `t or "text"`, e.g. `money`, `macaddr`, `point`). Net effect: all integer widths become type `integer`; plain `varchar` without length -> `varchar`.
4. **Serial/identity**: `serial = bool(identity) or ("nextval(" in default)`. If `serial` and base `integer` -> type `serial` and `default=None`. (MySQL auto_increment goes through the same path via `identity`.)
5. **Enums**: `enumValues` from metadata (PG enum types), or parsed from MySQL `enum('a','b')` type string (quote-doubling `''` handled).
6. **numeric(p,s)/decimal(p,s)**: regex on raw type -> `precision=p`, `scale=s or 0`; `numeric` with no (p,s) leaves both None.
7. `max_length = c.maxLength` if truthy else base-type length.
8. `default` stringified (None stays None; serial defaults dropped); `generated=True` if metadata `generated`; `identity_always=True` if `identityKind == "a"`. A generated column forced `nullable=True`.
9. Constraints:
   * `p`: stores pk column list.
   * `u` single column in cols -> `column.unique=True`; `u` multi-column (all columns known) -> appended to `unique_together`.
   * `f`: if `schema_name` and `refSchema` present and different -> warning `"<table>.<cols> references <refSchema>.<refTable> outside schema "<schema>". It is treated as a plain column, so loading may fail on that foreign key."` and the FK is skipped. Otherwise one `ForeignKey(column, ref_table, ref_column)` per zipped column pair (composite FKs become several single-column FKs).
   * `c` with `definition`: `_enum_from_check` (regex for `col = ANY (ARRAY['A'::..., 'B'::...])` or `col IN ('A','B')`) -> if the column exists sets `enum_values` (quote-unescaped); else `_assign_range_checks`: `_clean_check` (strip leading `CHECK`, remove `::type` casts incl. `::double precision`, `::character varying`, timestamp types, array/length suffixes, then 3x unwrap `(123)` and `(identifier)` parens, remove double quotes); split on ` AND `; for each clause containing `>= <= > < BETWEEN`, find column names that appear as whole words; if exactly ONE column is referenced, append the clause to that column's `check` joined with ` AND `. If nothing could be assigned -> warning `"<table>: check constraint "<definition>" is not automatically validated."`.
10. **Unique indexes** (`uniqueIndexes`): `icols` = index columns that exist; if `expression` present, also add every table column whose name appears as a whole word in the expression text. If `hasExpression` -> warning `"<table>: unique index <name> uses an expression (e.g. lower(col)); its plain columns are treated as unique, case-insensitively."` One column -> `column.unique=True` (stricter than a partial/expression index, so safe). Several columns -> appended to `unique_together` if not already present.
11. **Composite PK**: `len(pk_cols) > 1` -> `unique_together.append(existing pk cols)` and NO column is marked `primary_key` (composite PK is treated as a unique combination). Every PK column gets `nullable=False`. Single PK: `primary_key=True, unique=True`.
12. Returns `Schema(db_type, database, schema_name, target_id, tables, warnings, source, extracted_at=UTC isoformat)`.

`normalize_mongo_metadata(raw, database, target_id)`: warnings start with `"MongoDB metadata cannot reveal relationships. Cross-collection references are shown as missing, not guessed."`. Each collection gets `_id` column `Column(name="_id", type="objectId", primary_key=True, unique=True, nullable=False)`. If `validator.$jsonSchema.properties` exist: each property (skip `_id`) gets bsonType (`bsonType` or `type`, first of list, default `string`) mapped `int/long/integer->int`, `double/decimal/number->double`, `bool/boolean->boolean`, `date->date`, else `string`; `nullable = name not in required`; `enum_values` from `enum` (stringified); `max_length` from `maxLength`. Else the table has only `_id`, `needs_definition=True` and warning `Collection "<n>" has no schema validator. Provide a JSON Schema or define its fields manually.` Schema `source="boomi-pymongo"`, no FKs.

`service.discover_schema(t)`: see 1.2; PG schema name passed (`t.schema`) only for postgresql; direct-mode warning inserted at index 0. Note the `source` field is always `"boomi-jdbc"` for SQL even in direct mode.

---------------------------------------------------------------------------------------------------

#### 8. Generation engine

##### 8.1 `generator.py`
Constants: `LOCALES = {en_IN:en_IN, en_US:en_US, en_GB:en_GB, de:de_DE, fr:fr_FR}`; `COUNTRY` = India / United States / United Kingdom / Germany / France. Type groups (lower-case): `INT_TYPES={serial,bigserial,integer,int,bigint,smallint,long}`, `NUM_TYPES={numeric,decimal,float,double,real,number}`, `DATE_TYPES={date,timestamp,timestamptz,datetime}`, `TEXT_TYPES={varchar,text,string,char}`; helpers `is_int/is_num/is_date/is_text`.

* `parse_range(check)` -> `(lo, hi)`: `BETWEEN a AND b` -> both; else `>= n` -> lo=n, or `> n` -> lo=n+1; `<= n` -> hi=n, or `< n` -> hi=n-1 (regex search, so a clause with several comparisons uses the first of each kind).
* `coerce_value(col, value)`: converts scenario text to column type: booleans accept `true/t/1/yes/y` (case-insens) else False; int types `int(float(v))`; numeric `float`; ValueError -> original; else unchanged.
* `dependency_order(schema, selected) -> (order, cyclic, self_referencing)`: NetworkX `DiGraph` of selected tables with edge parent->child for FKs to other selected tables (self refs recorded separately). `nx.condensation` + `topological_sort`; components with >1 member -> `cyclic` list (skipped, never generated); singletons -> `order` (parents first). `self_refs` sorted unique.
* `required_parents(schema, selected)`: recursively adds referenced tables for NOT-NULL FKs whose parent is not selected (nullable FK or self-reference skipped); mutates `selected`, returns added names.

**`GenContext(schema, locale, seed=None, domain=None, pools=None)`**: `Faker(LOCALES.get(locale,"en_US"))` seeded with `seed` (or random int `< 2**31-1` from numpy); `numpy.random.default_rng(seed)`; state: `dataset`, `counters` (per-table key counter), `uniques` (`"table.col" -> set of lower-cased str values`), `pools` (`(table,col)->list[str]`), `composites` (`(table, group_tuple) -> set of key tuples`), `_no_pool`, `_fk_perm`, `table_map`.

Key helpers:
* `pick(seq)` uniform via `rng.integers`.
* `_uniq(table, col, make)`: up to 40 attempts calling `make(attempt)`; strings truncated to `max_length`; compared case-insensitively against the per-column set; fallback after 40: numbers -> `len(seen)+100000`; strings -> `base[: max(1, (max_length or 40)-7)] + "-" + (len(seen)+1)`, then right-truncated to max_length.
* `_recent(days_back, days_ahead=0)`: now(UTC) + uniform offset in `[-days_back, days_ahead]` days.
* `_tokens(name)`: split camelCase/non-alphanumerics into lower-case token set.
* `_texty(t)`: text type, or any type not in `{boolean,bool,uuid,json,inet,time,interval,bytea,objectid,date}` and not int/num/date/array.

**Numeric generation `_numeric(c, integer)`**: bounds from `parse_range(check)`; when no range known, defaults by name tokens: `year`: 2000-2025; `age` 18-80; price/amount/cost/total/salary/fee/balance/revenue 10-5000; qty/quantity/stock/count/units 1-100; percent/percentage/pct/ratio/rate/progress 0-100; rating/stars 1-5; latitude/lat -60..70; longitude/lng/lon -120..140; `port` 1024-65535; otherwise 0-1000. Only lo given -> max = lo+1000; only hi given -> min = min(0, hi). If `precision` set: `limit = 10**(p-s) - 10**-s`; clamp `[−limit, limit]`; if mn>mx then mn=mx. Integer: `rng.integers(ceil(mn), floor(mx)+1)`. Float: `round(triangular(mn, (mn+mx)/2 + (mx-mn)*0.1, mx), scale)` with scale = `c.scale` or 2.

**Name-hint text values `_by_name(table, col)`** (only for text-like columns; pool wins when present and pools not disabled via `_no_pool`; checked in this order, tokens `has()` exact-word, `near()` substring of name without underscores): email (`near email` -> `faker.email().lower()`), phone/mobile/tel/telephone/fax/msisdn -> phone_number, first/given/forename (or `firstname`,`givenname`) -> first_name, last/surname/family (or `lastname`,`familyname`) -> last_name, username/login/handle/nickname -> user_name, password/passwd/hash/digest/checksum -> sha256 truncated to max_length, token/secret/apikey/accesskey -> sha1 truncated, slug -> 3 words hyphenated, url/uri/link/href/website/homepage -> url, domain/hostname/host/subdomain/fqdn -> domain_name, ip/ipv4/ipaddress -> ipv4, color/colour -> hex_color if max_length<=7 else color_name, currency -> currency_code, language/lang/locale -> language_code, timezone/tz -> timezone, country -> country_code if max_length<=3 else locale country name (fallback `current_country()`), city/town -> city, state/province/region (and not status) -> state, zip/postal/postcode/pincode -> postcode, address/street/addr -> street_address, gender/sex -> Male/Female/Other, company/organization/organisation/org/employer/vendor/supplier/business -> company, job/designation/occupation/position (or jobtitle/roletitle) -> job, sku/barcode/isbn/ean/upc -> `bothify("????-########").upper()`, code/ref/reference/number/no with max_length<=30 -> `bothify("??-#####").upper()`, title/subject/headline/caption/label -> sentence (5 words, no trailing dot), description/notes/note/comment(s)/remarks/message/body/summary/bio/details/content/text/reason -> sentence if max_length<200 else paragraph, `name`: person-ish name tokens (full/display/person/contact/owner/author/customer/client/user/employee/member/staff/patient/student/teacher/manager/supervisor/head) -> name; else by table tokens: user/person/customer/employee/member/contact/staff/patient/student/teacher/author/profile/account tables -> name, company/organization/vendor/supplier/provider/tenant/client/business/employer/partner/brand tables -> company; file/document/image/photo -> file_name; fallback `catch_phrase`. No match -> None.

**Keys `next_key(table, col)`**: increments the per-table counter; objectid -> 24 lowercase hex; uuid -> `faker.uuid4()`; int types -> `idx+1`; otherwise string `PREFIX{101+idx}` where PREFIX is the first 3 letters of the table name (non-letters stripped, uppercased; "ID" if empty).

**`_bump(v, attempt, col)`**: for attempts <3 returns v unchanged. Dates (str ISO) -> add `attempt` days + minutes (date format for `date`, ISO ms + `Z` otherwise); structured types (uuid, inet, json, time, interval, bytea, objectid, arrays) unchanged (next attempt draws a fresh value); strings append `attempt`; ints add `attempt*7919`; floats add `attempt*0.37` rounded 2.

**`value(table, col, use_pool=True)`** (repair use): `_raw` with pool toggle, truncated to max_length.

**`_raw(table, col)`** order: enum_values -> pick; text-like -> name hint; boolean (`true` prob 0.9 if default == "true" else 0.5); int -> `_numeric`; num -> `_numeric`; `date` -> `_recent(300).date().isoformat()`; other date types -> ISO ms with trailing `Z`; uuid -> uuid4; json -> `{"key": word, "value": 0-999}` as JSON string; inet -> ipv4; time -> `faker.time()`; interval -> `"<1-119> minutes"`; bytea -> `"\\x" + 8 hex`; `array:<t>` -> list of 1-3 values from the inner type (max_length inherited); else 1-3 faker words truncated to `max_length or 60`.

**`_from_column(table, col)`**: unique non-PK -> `_uniq(..., lambda a: _bump(_raw(...), a, col))`, else `_raw`.

**`_unique_fk(table, col, fk, pool)`**: one-to-one FK permutation: builds a shuffled list of parent keys not yet used (state per `(table, col)`, rebuilt if parent pool size changed keeping the used set); hands out each parent at most once; when exhausted returns None if nullable else a random parent key.

**`add_row(table_name, forced=None, parents=None)`**: composite uniqueness loop: groups = `unique_together`; up to 250 attempts (1 if no groups) rebuilding via `_build` and resetting `counters[table]` to the pre-call value each attempt; accepted when none of the row's composite keys (tuples of `str()`, only groups with all columns non-null) is in `composites[(table, group)]`; then records the keys and appends the row to `dataset[table]`; returns row.

**`_build(table_name, forced, parents)`**:
1. For each FK whose referenced table is in `parents` (and column not forced, not self-ref): copy the parent's `ref_column` value.
2. **Anchor FKs**: for an FK (not done/forced/self-ref) whose parent table is generated and which has "sibling" FKs (another FK of this table points to a table that this parent table also references): choose one random parent row, take `row[f.column] = parent[f.ref_column]` and derive every sibling FK column from the parent's corresponding column (so e.g. `order.customer_id` and `order_item.customer_id` stay coherent).
3. For each column (skip forced/done): forced values are used as-is; `generated` columns skipped (DB computes them); PK without FK -> `next_key`; FK columns: pool = own rows for self-ref else parent dataset; unique FK (non-self) with pool -> `_unique_fk`; else random parent value or None if no pool; nullable columns get None with prob 0.15 (draw happens only for non-key, non-FK columns); otherwise `_from_column`, string values truncated to max_length.
4. `_order_dates`.
Note: FK columns that are PK get the FK value; composite-PK columns are not flagged `primary_key`, so they are generated as ordinary columns/FKs with composite uniqueness handled by `add_row`.

**`_order_dates(table, row, forced)`**: date columns whose tokens intersect EARLY (`start, starts, begin, begins, from, opened, open, created, issued, joined, registered, submitted, ordered, placed, scheduled, booked, birth, dob`) and not LATE; LATE tokens: `end, ends, until, to, closed, close, updated, modified, expires, expiry, expiration, due, completed, finished, resolved, deleted, delivered, shipped, reviewed, approved, paid, cancelled, canceled, last, valid` (late columns not in `forced`). `floor = max(parsed early)`; any late value earlier than floor is moved to floor + 1-119 days + 0-23 hours (date or ISO-ms-Z format).

**`sample_row`** builds a row then removes it and restores the counter. **`pk_of(table,row)`**: string of the single PK value.

**`create_chain(table_name, forced, depth, created)`** (used by Mode 2 variants; no current caller in app code): creates a row plus fresh parents `depth` levels up (deeper ancestors reuse random existing rows; if no pool exists it always creates one); anchors processed first; sibling FK parents resolved to the existing parent row whose key matches the created parent's sibling column; appends `{table, key}` to `created`.

##### 8.2 `pipeline.py`
**`JobState` dataclass**: `job, schema, dataset={}, order=[], links={}, coverage=None, adjustments=[], unsupported=[], requested={}, started=0.0, api_base_url=None, has_spec=False, ctx=None, ai_source="rules", tc_checks=[], batch_ref=""` (batch_ref unused).

**`generate_tables(st, counts, bp)`**:
1. `ctx = GenContext(schema, bp.locale_hint if bp else cfg.locale, cfg.seed, bp.domain or description, pools_from(bp))`.
2. `want = {t: n for t,n in counts if n > 0}`; `selected = set(want)`; `required_parents` adds missing NOT-NULL-FK parents with **5** records each and adjustment `Added parent table "<p>" with 5 records because a selected table has a required foreign key to it.`
3. `st.requested[t]` = user's requested count (or 5 for auto-added).
4. `dependency_order`; cyclic tables -> unsupported `"<t>: part of a cyclic relationship. Skipped instead of bypassing constraints."`; self-referencing -> unsupported `"<t>: self-reference handled by leaving the first record's parent null."`.
5. **Feasibility / count reductions** per table in order (n=want[t]): (a) unique non-PK enum column with `n > len(enum)` -> adjustment `"<t>: <n> records impossible, unique column "<c>" only has <k> permitted values. Proposed <k>."`, n=k; (b) unique FK column with `want[ref] < n` -> `"<t>: unique foreign key "<c>" needs <n> distinct <ref> records, only <m> exist. Proposed <m>."`, n=m; (c) composite unique made only of FK columns: `combos` = product of `want.get(ref, existing rows or 1)` over distinct referenced tables; if `n > combos` -> `"<t>: unique combination (a, b) allows only <combos> distinct rows with the available parent records. Proposed <combos>."`, n=combos. Final `want[t]=n`.
6. **Scenario slot allocation**: `forced_by[t] = [{} * want[t]]`. For each scenario (table selected, column exists, value valid for enum if the column has enum_values) group by `(table, column)`; shuffle slot indices by `ctx.rng.permutation`; for each `(value, count)` assign `coerce_value(col, value)` to the next unused slots until slots run out; the remaining slots get a random value from the non-requested enum values (`others`, or all values if none); for boolean columns with one scenario the remainder gets the opposite value (so the count is exact). Scenario values that are not enum values on a non-enum column are still forced (coerced).
7. Generation: for each table in dependency order, for each forced dict: if the table has a self-referencing FK and has no rows yet, the first row is added with that FK = None; else `ctx.add_row(name, forced)`. `dataset.setdefault(name, [])`.
8. `st.dataset = ctx.dataset`; `adjustments.extend(repair_dataset(schema, ctx, order))`.

**`restore_context(st)`** (for jobs reloaded from disk, used by generate-missing): fresh `GenContext` with seed `(cfg.seed or 0) + total row count`, copies the dataset, `counters[t]=len(rows)`, rebuilds `uniques` for unique non-PK columns.

**`build_report(st, duration_ms)`**:
* checks = `st.tc_checks` for testcase mode else `validate(schema, dataset, coverage, test_cases)`.
* `pct(id)` = `round((checked-failed)/checked*1000)/10` or 100.0 if checked==0; `data_type_validity=pct("type")`, `relationship_integrity=pct("fk")`, `uniqueness_violations = checks["unique"].failed + checks["pk"].failed` (0 if "unique" absent, as in Mode 3).
* `per_table` = `PerTable(table, requested=st.requested.get(t, len(rows)), generated=len(rows))` for every dataset table.
* `failed = any(check.status=="failed") and mode != "testcase"`. In testcase mode every failed check is downgraded to `warning`. `warn = any warning or bool(adjustments)`. Status: `failed` / `partial` (warn) / `completed`.
* `test_coverage` when `job.test_cases is not None`: `by_category` for the four categories, `total`, `with_prerequisites` (cases with prerequisite_records), `ready_to_export` (ready), `needing_rules` (needs_rules and not ready).
* `Report.scenario_coverage = st.coverage`, `unsupported_constraints = st.unsupported`, `adjustments = st.adjustments`.
* **Mode 3 differences**: checks come from `tc_validate`; no dataset so `records_*`=0; failures become warnings so export is never blocked; `unsupported_constraints` empty (finalize_unsupported not called); `data_type_validity/relationship_integrity` = 100.0.

`refresh_coverage(st)` = `scenario_coverage(dataset, schema, blueprint.scenarios)`. `finalize_unsupported(st)` = dedupe(`st.unsupported` + `validator.unsupported_constraints(schema)`).

##### 8.3 `repair.py` (`repair_dataset(schema, ctx, order, allow_delete=True) -> notes`)
Processes tables in dependency order (plus any dataset tables not in order). For each table `_repair_table` returns the number of dropped rows; note per table `"<t>: <n> record(s) removed because no combination satisfying the table's unique / foreign-key rules could be found."` Steps per table:
1. **Cell level** (skip generated columns): None where not nullable/missing -> FK column gets a random existing parent key (None if no parents), else new `ctx.value(use_pool=False)` passed through `_fit`; enum values outside `enum_values` -> random valid; values failing `_type_ok` -> regenerated; every value passed through `_fit` (truncate strings to max_length; clamp numeric to `parse_range(check)`, int-cast for int types).
2. **FKs**: non-null FK value not among parent keys -> replaced by a random parent key (excluding own key for self-refs; first row of a self-referencing table is exempt), else None if nullable, else row marked for dropping.
3. **Single-column uniqueness** (PK and UNIQUE, non-generated), case-insensitive on `str(value).lower()`: first occurrence keeps the value; later duplicates get a new value: FK column (non-self) -> an unused parent key from the free list; enum column -> unused enum value; else up to 150 attempts of `_fit(_bump(ctx.value(...), attempt))` that is unused and `_type_ok`. If none: set NULL if nullable, else drop the row (if `allow_delete`).
4. **Composite uniqueness** over `unique_together` (also composite PKs and unique indexes): duplicates (rows with all-non-null keys, case-insensitive) are fixed by up to 400 tries: pick a random column of the group, assign a new value (FK -> random parent key; enum -> random; else bumped fresh value), accept if the tuple is new and `_unique_cols_ok` (no clash on that column's own single-column unique); else restore; unfixable rows dropped.
5. **Drop** collected rows from the dataset list in place; then re-point or null same-table self-references that referenced a dropped row (nullable -> None, else first existing key).

##### 8.4 `validator.py`
**`_type_ok(col, v)`** ("valid here means loads there"): objectid = 24 lowercase hex str; uuid = canonical 8-4-4-4-12 hex str; boolean = `bool`; int types = `int` and not bool; numeric = int/float (not bool) and, if `precision` set, `abs(v) < 10**(precision-scale)`; `date` = `YYYY-MM-DD` valid date; other date types = str starting `YYYY-MM-DD[T ]HH:MM` and parseable by `fromisoformat` (after `Z`->`+00:00`); time = `time.fromisoformat`; json = parseable str (or serializable object); inet = `ipaddress.ip_interface`; interval = `^\d+ (second|minute|hour|day)s?$`; bytea = `^\\x(hex pairs)*$`; array = list; text types = str; anything else True.

**`validate(schema, dataset, coverage=None, test_cases=None)`** computes counters over all tables present in the dataset and returns exactly nine `ValidationCheck`s in this order, ids and labels:
1. `type` "Data type matches field" - every non-null value through `_type_ok`.
2. `required` "Required fields not null" - every cell: null fails unless `nullable` or `missing`.
3. `length` "String length within limit" - strings with `max_length`.
4. `pk` "Primary key unique" - non-null values of single-column PK columns, via `str()` (case-sensitive).
5. `fk` "Foreign key references a parent" - non-null FK values must exist in the parent table's `ref_column` set (own rows for self-refs).
6. `unique` "Unique constraint holds" - single UNIQUE non-PK columns plus every `unique_together` group (all columns non-null).
7. `enum` "Enum and check constraints" - values in `enum_values`, and numeric values inside `parse_range(check)`.
8. `scenario` "Scenario counts match request" - `warning` if any scenario result != Covered (`failed` = number of uncovered), `passed` when all covered, `skipped` (checked 0) "No scenarios requested" when no coverage supplied.
9. `linkage` "Test-case linkage exists" - when `test_cases is not None` (Mode-2 style with `prerequisite_records`): `failed` if a prerequisite key is not found among any value of the table rows; else `skipped` with detail "Mode 3 only". (In practice prerequisite_records is always empty.)
Failure description: `status="failed"` and `detail = "<failed> of <checked> checked values failed (<table.column> x<n>, ...top 5 locations)"`; success detail `"<checked> values checked"`. Composite groups are located as `table.(a,b)`. The key mapping from check id to counters is `required->req, length->len, unique->uq, enum->en, others identity`.

**`scenario_coverage(dataset, schema, scenarios)`**: per scenario: table/column missing -> `Unsupported` ("Schema has no t.c. The requested state cannot be represented."); value not in enum -> `Unsupported` ("<v> is not permitted by the <c> constraint (<list>)."); else count rows where `str(value).upper() == scenario.value.upper()`; `Covered` if >= count, `Missing` if 0, else `Partial`; note `"<n> more required."`.

**`unsupported_constraints(schema)`**: for each column with a `check` where `parse_range` finds neither bound -> `'<t>.<c>: check "<check>" is not automatically validated'`; tables with `needs_definition` -> `"<t>: no validator, fields were not discovered"`; for Mongo `"Cross-collection references are not discoverable from MongoDB metadata"`; plus schema warnings that contain `not automatically` or `composite`.

##### 8.5 `planner.rule_blueprint(schema, config) -> Blueprint`
* `counts` from `config.tables`; `scenarios` start as `config.scenarios`.
* Description split by `[,;\n]|\band\b|\.(?=\s|$)`; each clause matched `(?:generate|create|add|include|with)?\s*(\d[\d,]*)\s+(.+)$`. The tail text is matched to a table by `find_table`: table name aliases (all suffixes of the underscore-split name, plus singularized last word, sorted longest first; `ies->y`, trailing `s` stripped); the tail text must END with an alias; the leftover prefix is the "rest". No rest -> `counts[table] = n` (overrides the config count). With rest -> scenario: state = last word of rest uppercased; column = first enum column containing that value (case-insens) else the column named `status` else literal `"status"`; `Scenario(table, column, value=state, count=n)`.
* `domain` = stripped description or "Generic application (no description supplied)". `locale_hint`: `en_IN` if text matches `india`; `en_GB` if `uk|british|england` words; else `config.locale`.
* `column_rules`: up to 8 `"Weighted choice over A / B / C"` for non-PK enum columns (informational only; the generator does not read them).
* notes: e-mail-column note (first 3 cols), scenario total exceeding the table's requested count note `"Scenario total for <t> (<n>) exceeds the requested record count (<m>); some scenarios will be reported as missing."`, and `"No application description given, so only scenarios and counts were applied."`.
* Returns `Blueprint(domain, locale_hint, table_counts=[counts], scenarios, column_rules, notes)`.

##### 8.6 `ai.py`
* `available()` = key present. `schema_summary(schema)` emits `- table(col:type PK required unique enum=A|B check=...; ...) FKs: col->ref.col` (no data, no credentials).
* `llm_json(system, prompt, timeout=60)`: `httpx.post(f"{OPENAI_BASE_URL}/chat/completions", json={"model", "temperature": 0.4, "response_format": {"type":"json_object"}, "messages":[system,user]}, headers={"Authorization": "Bearer <key>"}, timeout)`; `raise_for_status`; `json.loads(choices[0].message.content)`; ANY exception -> log `LLM call failed, using rule-based planner: <Class>` and return `None`. The key never appears in the body.
* `BLUEPRINT_SYSTEM`: "You design synthetic test-data generation blueprints for a database. Reply with ONE JSON object only, no prose. Never invent tables or columns; use only those provided. Never include credentials."
* `plan_blueprint(schema, config) -> (Blueprint, "ai"|"rules")`: always computes `base = rule_blueprint`; returns `(base,"rules")` if no key or description blank. Prompt contains the description, schema summary and the JSON shape `{domain, localeHint (en_IN|en_US|en_GB|de|fr), scenarios[{table,column,value,count}], valuePools[{table,column,values (max 25)}], columnRules[{table,column,rule}], notes[]}` plus rules ("scenarios only for workflow states explicitly requested; value must be one of the column's enum values; valuePools only for free-text columns (not enums, keys or e-mails)"). `raw` None -> note `"AI service unavailable, used rule-based interpretation."` -> rules. `Blueprint.model_validate({**raw, "tableCounts": []})` (AI table counts are always discarded) `ValidationError` -> note `"AI returned an invalid blueprint, used rule-based interpretation."`.
* `_merge_blueprint(schema, base, ai)`: AI scenarios: unknown table -> note `Ignored AI scenario for unknown table "<t>".`; value upper-cased and added if `(table,column,VALUE)` not already present (rule-parsed ones win, so they dedupe). Value pools: kept only for existing, non-enum, non-PK, non-FK columns whose type is not integer/numeric/boolean/date/timestamp; values must be non-empty strings, truncated to `max_length`, max 25. Column rules: only for existing table+column; final `(base.rules + ai.rules)[:12]`. `locale_hint` accepted only from the whitelist else base. `table_counts` always from base. notes = base notes + `ai.notes[:4]`.
* `TESTPLAN_SYSTEM`: "You are a senior QA engineer writing API test cases for requests that already exist in the user's collection. Reply with ONE JSON object only. Refer to endpoints only by the index given and to request fields only by the names given. Expected behaviour that depends on permissions, duplicate policy or business rules that are not in the schema or the supplied rules MUST set needsRules=true."
* `plan_extra_cases(endpoints, schema, feature, categories, rules)`: None if AI unavailable. Prompt lists endpoints `[i] METHOD path fields: a, b | table T`, the DB constraints of the matched tables (via `schema_summary`), feature, categories and business rules; asks for `{"cases":[{endpoint(index), category, title, expected, expectedStatus("2xx|4xx|exact"), needsRules, set{field:value}, omit[fields], preconditions[]}]}`, "at most 20 cases", edits to the example body only. Timeout 90 s.

##### 8.7 `jobs.py`
**Stage lists** (id, label, layer):
* `fast`: handoff "Record generation-job handoff" (Boomi); schema "Validate normalized schema" (Python); graph "Build dependency graph (parents first)"; rows "Generate parent then child records"; validate "Run nine validation checks"; store "Store dataset for paginated preview" (all Python).
* `scenario`: handoff "Supply metadata and job context" (Boomi); ai "AI builds the generation blueprint" (AI); bp "Validate blueprint against schema (Pydantic)"; graph; rows "Generate interconnected records"; scenarios "Apply scenario rules and verify counts"; validate; store.
* `testcase`: handoff (Boomi); parse "Read the Postman collection / API specification"; match "Match endpoints to tables and constraints"; sample "Read sample rows from your database (optional)"; ai "AI adds business-rule test cases" (AI); build "Build test cases and request fixtures"; validate "Run test-case validation checks"; store "Store test cases" (Python).

**`create_job(schema, config, owner)`**: id `job_<token_hex(5)>`; `Job` with all stages pending; `JobState(started=perf_counter())`; `store.put_job`; daemon thread `_run`. Returns id.

**`_run`**: for each stage: mark running, `sleep(0.2)` (cosmetic), do the stage's work, mark done with a detail string. Stage behavior:
* `handoff`: detail `Job <id> registered with <n> tables of metadata` (purely cosmetic; NO Boomi call).
* `ai` (scenario): `ai.plan_blueprint` -> `job.blueprint`, `st.ai_source`; detail "Blueprint returned by the hosted LLM" or "AI unavailable, rule-based interpretation used".
* `bp`: detail count of scenarios/table counts/pools.
* `rows`: counts = blueprint.table_counts in scenario mode (if blueprint) else `cfg.tables`; `pipeline.generate_tables`; detail `<n> records created`. (Scenario mode ignores `cfg.tables` unless the rule blueprint copied them: `rule_blueprint` does copy `config.tables`.)
* `scenarios`: `refresh_coverage`; detail `<covered>/<total> covered`.
* `parse`: requires `cfg.test_case`; text = `collection_text or open_api_text`; blank -> `ValueError("Add a Postman collection or an OpenAPI file. Test cases are written against its real endpoints.")`; `parse_api_source`; sets `st.api_base_url = tc.api_base_url or src.base_url or None`, `st.has_spec = True`.
* `match`: `match_tables`; detail "n of m requests matched to a table".
* `sample`: if `use_db_samples` and `schema.target_id`: `get_target(target_id, owner)` (missing -> `ValueError("The saved connection for row sampling was not found.")`), tables = sorted matched tables among selected endpoints, `read_samples`, notes appended to `st.adjustments`; else detail "Skipped: values come from your collection".
* `ai` (testcase): `Planner(src, schema, categories, samples, rules_supplied=bool(business_rules.strip()))`; `cases = planner.plan(selected_endpoints or None)`; chosen endpoints; `raw = ai.plan_extra_cases(...)`; `st.ai_source`; extra cases through `from_ai`; detail "<n> extra case(s) from the AI" or "AI unavailable: rule-based cases only".
* `build`: `job.test_cases = finalize(cases)`; empty -> `ValueError("No test cases could be built from the selected requests and categories.")`; detail "<n> test cases for <m> request(s). No records are written to your database."
* `validate` (testcase): `st.tc_checks = run_checks(schema, src, test_cases, categories, {table: n rows for tables with samples})`; `job.report = build_report(...)`; detail "<k> of <n> passed".
* `validate` (other): `finalize_unsupported`; `build_report`; detail "<k> passed".
* `store`: `store.save_job(st)`.
After all stages: `job.status = job.report.status` and save again. **Errors**: any exception -> logged; every stage currently `running` marked `failed` with `str(e)`; `job.error = str(e)`; `job.status = "failed"`. (So Mode 3 never reaches `failed` through checks; only by exceptions such as missing collection / unparsable file / zero cases.) Note a failed job is not saved to disk.

**`generate_missing(st)`**: `ctx = st.ctx or restore_context(st)`; for each coverage with result Missing/Partial: skip if the table has an FK to another table that has no rows; add `scenario.count - generated` rows with `forced {column: value}` (raw string value, not coerced); bump `st.requested[table]`; `refresh_coverage`; remove adjustments starting with "Scenario"; remove blueprint notes starting with "Scenario total"; rebuild report (keeps old duration); `status = report.status`; `save_job`. No repair pass is run on the added rows.

##### 8.8 `exporters.py`
`FORMATS = {xlsx, csv-zip, json, sql-postgres, sql-mysql, postman, testcase-xlsx, pytest, mapping-report, report-json, report-xlsx}`. `build_export(fmt, schema, dataset, order, report, cases, api_base) -> (bytes, filename, media_type)`; `names` = tables in `order` present in dataset. Prefix `STAMP="atom_foundry"`.
* `xlsx` -> `atom_foundry_data.xlsx`: one sheet per table (title sanitized of `[]*?/\:`, <=31 chars); header from first row's keys (empty table -> empty sheet); None -> empty cell; list/dict -> JSON string.
* `csv-zip` -> `atom_foundry_data.zip`: `<table>.csv` (header from schema column order, `\n` line endings, None -> empty) + `schema_manifest.json` (`database`, `dbType`, tables dumped by alias excluding None, `loadOrder`) + `validation_report.json`.
* `json` -> `atom_foundry_data.json`: `{table: rows}` indent 2.
* `sql-postgres` -> `atom_foundry_postgres.sql` (text/plain), `sql-mysql` -> `atom_foundry_mysql.sql`: header comments (dialect, database, schema if PG non-public, UTC timestamp), `BEGIN;` / `START TRANSACTION;`, per table comment `-- <t>: <n> rows`, multi-row `INSERT INTO <qual>(<cols>) VALUES` chunks of 100 rows, then `COMMIT;`. Identifier quoting `"x"` (PG) / backticks (MySQL); PG non-public schema qualifies as `"schema"."table"`. Literals: None -> `NULL`; bool -> `TRUE/FALSE`; numbers raw; lists -> `'{"a","b"}'` array literal; other -> quoted string with `'` doubled. (Dataset columns are taken from the first row's keys, so generated columns are absent; MySQL gets the same literal style including array literals.)
* `testcase-xlsx` -> `atom_foundry_test_cases.xlsx`: sheets "Test cases" (columns `Test ID, Category, Title, Endpoint, Table, Preconditions (newline-joined), Steps (numbered), Expected result, Expected status (single fixture status, or "a -> b" chain), Request body (pretty JSON), Needs rules Yes/No, Ready "Ready"/"Needs input"`) and "Endpoint coverage" (per endpoint: `Endpoint, Table ("(not matched)" if none), positive, negative, boundary, workflow, Total`).
* `mapping-report` -> `atom_foundry_endpoint_coverage.xlsx` (only the coverage sheet).
* `postman` -> `atom_foundry_postman_collection.json` (Postman v2.1.0 schema): `info.name = "ATOM DATA FOUNDRY - test cases (<database>)"`; collection variables `baseUrl` (= `api_base_url` or `http://localhost:8000`), `authToken` (""), `createdId` (""); folders named `Positive/Negative/Boundary/Workflow` (category capitalized, only categories present, in encounter order). Each case with a fixture becomes an item named `"<id> <title>"`; chains become a folder of items `Step n: METHOD path`. Each request: leftover single-brace `{id}` converted to `{{id}}` (not touching `{{...}}`); headers from fixture, `Content-Type: application/json` added when a body exists and none set; `url.raw = "{{baseUrl}}" + path`, `host ["{{baseUrl}}"]`, `path` segments; raw JSON body with language json; a `test` event: `pm.test("Status is <e>", ...)` using `within(lo, lo+99)` for `Nxx` or `.to.eql(code)` otherwise (default `2xx`); a fixture note `capture-id:<pk>` adds a script setting collection variable `createdId` from `response.data[pk] ?? id ?? pk`.
* `pytest` -> `test_atom_foundry.py` (text/x-python): header with `BASE_URL`/`AUTH_TOKEN` env vars, `_headers` (replaces `{{authToken}}`), `_expect` (xx range or exact code), `_send` (replaces `{{createdId}}`, then other `{{var}}`/`{var}` path variables with `os.environ[VAR.upper()]` default `"1"`; `httpx.request(..., json=body, timeout=30)`). One `def test_<id.lower()>_<slug>():` per case with a fixture (slug = title lowercased non-alnum -> `_`, <=48 chars; docstring has title and Expected with `"` replaced by `'`), body calls `_send(method, path, body, headers, status, created)` for each request (chain or single); `capture-id` steps store `created`.
* `report-json` -> `atom_foundry_report.json` (`Report` by alias, indent 2); `report-xlsx` -> `atom_foundry_report.xlsx`: sheets Summary (Metric/Value rows: Database type, Database, Tables discovered, Generation mode, Records requested/generated, Data-type validity %, Relationship integrity %, Uniqueness violations, Status, Duration (ms)), Checks, Per table, and Scenario coverage when present.
* XLSX media type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. Unknown format -> `ValueError`.

---------------------------------------------------------------------------------------------------

#### 9. Mode 3 in depth

##### 9.1 `apisource.py`
Dataclasses: `Endpoint(method, path, name="", folder="", body: dict|None, headers: dict, required: list[str] (OpenAPI), ok_status="2xx", table: str|None)` with `key = "METHOD path"`, `has_path_param()` (`{` in path), `resource()` (path without trailing `/{param}`); `ApiSource(kind "postman"|"openapi", title, base_url, endpoints)`.

* `parse_api_source(text)`: text starting with `{` -> `json.loads`, else `yaml.safe_load`; failure -> `ValueError("The file is not valid JSON or YAML: <120 chars>")`; non-dict -> `ValueError("Unrecognised file. Provide a Postman collection (v2.x) or an OpenAPI / Swagger document.")`; `item` list -> Postman (empty -> `ValueError("The Postman collection contains no requests.")`; title `info.name` default "Collection"; base_url = most frequent base seen); `paths` key -> OpenAPI (no operations -> `ValueError("The OpenAPI document has no operations.")`); else the unrecognised error.
* **Postman walk**: nested `item` folders -> folder path `"A/B"`; request URL: strip query; if it starts with `http(s)://host` or `{{var}}` the base is that prefix and path the rest (default "/"); else from `url.path` array or the raw string forced to start with `/`. `_path_params`: `/:id` -> `/{id}`, `{{x}}` -> `{x}` (path only). Body: raw JSON object (non-dict -> None; invalid -> None), `urlencoded`/`formdata` -> key/value dict ignoring disabled. Headers: enabled headers except `content-length`/`host`, then masked: names (case-insens) in `{authorization, x-api-key, api-key, cookie, x-auth-token, proxy-authorization}` get value `{{authToken}}` (secrets are never stored/exported). `ok_status` = first documented saved response code in 200-299 else `2xx`.
* **OpenAPI**: `base` = `servers[0].url` or (Swagger2) `schemes[0]://host+basePath`; for each path and method in `get, post, put, patch, delete`: `$ref` (`#/...` with `~0/~1` unescape, depth 12) resolved; request body from `requestBody.content["application/json"]` (else first content type) or Swagger2 `in: body` parameter; example body built by `_example` (priority `example`, `default`, first `enum`, `allOf` merge, `oneOf/anyOf` first, object -> properties excluding `readOnly` (depth<=6), array -> single-item list, integer -> `minimum` or 1, number -> `minimum` or 1.5, boolean True, `date-time` "2025-01-15T10:30:00Z", `date` "2025-01-15", `uuid` "3fa85f64-5717-4562-b3fc-2c963f66afa6", `email` "user@example.com", string "sample" (cut to maxLength)); body used only if it is a dict; `required` = schema `required` list; `ok_status` = first `2xx` numeric response code else `2xx`; headers: `Content-Type: application/json` when body exists; `Authorization: {{authToken}}` if the operation or document has `security`; `name` = summary or operationId; `folder` = first tag.
* **Matching `match_tables(source, schema)`**: for each endpoint, path segments (excluding `{..}` params and version-like segments `api|v\d+(\.\d+)?|rest|public`) are normalized (`lower`, singularized: `ies->y` if len>4, trailing `s` removed unless `ss` and len>3, then non-alnum stripped). For each table `tn = norm(table)`: score +2.0 if `tn` equals last segment / last+"s" / endswith last / (len(last)>3 and last in tn) and `tn.endswith(last)` (else +1.0 for the contained case); else +0.5 if any earlier segment (len>3) is a suffix of `tn`. Body keys: count keys that map to a column (`norm(key) == norm(column)`); if hits >= 2 or (hit and exactly 1 key): `+2.0 * hits / len(keys)`. Best table with score >= 1.0 wins (`endpoint.table`), else None. (`key_to_column` ignores case/underscores: `crontabId` <-> `crontab_id`.)

##### 9.2 `tc_planner.py`
Constants: `INT_RANGE` per int type; `ORDER = [positive, negative, boundary, workflow]`; `PER_ENDPOINT = {positive: 5, negative: 14, boundary: 8}` (kept per endpoint and category; workflow is not capped per endpoint); `MAX_CASES = 300`; `BAD_ID = 987654321`; status regex `^[2-5]\d\d$|^[2-5]xx$`.

`Planner(source, schema, categories, samples=None, rules_supplied=False)`:
* `required(ep)`: request fields known required = OpenAPI `required` keys present in body + body keys whose matched column is NOT NULL, not PK, not generated, and has no default; second value = `known` (table matched or OpenAPI required exists).
* `make(...)` builds a `TestCase` (id blank, `fixture` = first of chain or a new `Fixture`, `requests`=chain, `endpoint=ep.key`): `ready = (not needs_rules) or rules_supplied`; `readiness_note` "Ready to run" / "Ready: expected behaviour taken from the supplied rules" / "Needs application rules: the schema and collection cannot define this behaviour". Default preconditions `["None"]`; default step "Send METHOD path[ with the request body below]".
* `base_body(ep)`: deep copy of example body; with a sample row, any FK column's value is replaced by the sample row's FK value (so parents exist).
* `for_endpoint(ep)` (per endpoint):
  * Path params add a precondition about an existing record; GET with `{param}` and a sample row uses `re.sub(\{[^}]+\}, <sample pk>)` as the path (precondition "Uses a record that exists in your database").
  * **positive** (not for DELETE): "valid request" (`<label>: valid request`, expected `Accepted (<status>) and the response matches the contract` or "Accepted (HTTP 2xx)..." - `_ok_text`), only-required-fields variant (if mutating POST/PUT/PATCH with body, `known`, required and optional fields present), up to 2 enum columns each with up to 2 alternative enum values (`<label>: <k> = <v>`).
  * **negative** (`_negatives`): for mutating requests: POST/PUT "missing <k>" for up to 6 required fields (or first 3 body fields when not known; `needs_rules` when not known) expecting 4xx; "<k> is null" for first 3 required fields; up to 4 "wrong type" cases (boolean -> "not-a-boolean", numeric -> "abc", date-like -> "not-a-date", uuid -> "not-a-uuid"); first enum field -> "is not an allowed value" with `INVALID_VALUE`; up to 2 FK columns -> "references a record that does not exist" (ghost = 987654321 for ints, all-zero UUID for uuid, "NO_SUCH_PARENT" otherwise); for POST, the first unique non-PK field in the first 30 body keys -> "duplicate <k>" (with a sample row: uses the existing value, precondition mentions existing record; without: a 2-step chain POST ok -> POST again 4xx, precondition "Run on a test environment: the first request creates a record"); POST/PUT -> "empty body" (`{}`, needs_rules when not known). For any endpoint with a path param: "record does not exist" (path id 987654321) and "malformed id" (`not-an-id`) expecting 4xx. If a masked `Authorization` header is present: "no credentials" (header removed) expecting 4xx (401/403).
  * **boundary** (mutating only, table must be matched): up to 4 non-PK, non-generated columns: text with `max_length` -> at max length (`"a" * n`, accepted) and over (n+1, 4xx); int non-FK -> at maximum (check hi or type max) accepted, above maximum 4xx, and below minimum 4xx when a lower check bound exists; numeric with `precision` -> largest allowed value accepted and `10**whole` rejected; then one "empty string" case for the first NOT NULL, non-PK, non-enum text column with `needs_rules=True`, expected 4xx and "Rejected or accepted according to the application's blank-value rule".
  * Kept = first N per category per `PER_ENDPOINT`.
* `workflows()`: group endpoints by `resource()`; a group qualifies when it has a POST without path param and with a body. Items with path params of the same resource are indexed by method. Chain steps use path id placeholder `{{createdId}}`; the create step carries note `capture-id:<pk column or "id">`. Cases: "create, then retrieve it" (GET), "create, then update <field>" (PATCH or PUT; field = first string body field that is non-unique, non-enum text, non-PK, with ` updated` appended and length trimmed; PATCH sends only that field, PUT sends the full body; followed by GET if exists), "create, delete, then confirm it is gone" (DELETE then GET expecting 4xx; text varies if no GET), "create, then it appears in the list" (GET collection path). Expected statuses `2xx`/documented ok codes.
* `plan(selected=None)`: per-endpoint cases for selected endpoint keys (all if none) plus workflow cases (only if "workflow" in categories and `case.endpoint` in the selected keys).
* `finalize(cases)`: dedupe by JSON signature of (category, endpoint, fixture path, fixture body, chain dump, sorted header keys); stable sort by category order; cut to 300; ids `TC001`...
* `from_ai(raw, planner, eps)`: up to the first 40 `cases`; `endpoint` index into the chosen endpoint list; category must be in the requested categories; endpoint must have a body; `set` accepted only for existing body keys with scalar/None values; `omit` only for existing keys; case skipped if neither; body = base body with edits; status must match the status regex else `4xx` for negative or the endpoint's ok status; title cut 160, expected cut 240, `needs_rules` from AI, preconditions max 4, a generated step text. Errors in one case skip only that case.

##### 9.3 `tc_validate.py` (advisory only; statuses downgraded to warning in the report)
`body_problems(schema, table, body, partial=False)`: for each body key mapped to a column: null on NOT NULL/no default/non-PK/non-generated -> "<k> is null"; wrong type via `_type_ok`; length; int range by type; enum membership; numeric check range; blank string on NOT NULL text -> "<k> is blank"; FK sentinel values (987654321, zero UUID, NO_SUCH_PARENT) -> "<k> points to no <ref>"; if not `partial`, NOT NULL columns without default and missing from the body -> "<c> is missing".
`run_checks(schema, source, cases, categories, tables_with_samples)` returns:
1. `endpoints` "Every case targets a request in your collection" (cases whose endpoint key not in the source; failed if any).
2. `positive` "Valid requests satisfy the database rules": POST positives with body and table; excluding "is missing" problems for the "only the required" variant; warn-level.
3. `negative` "Negative cases really break a rule": cases with 4xx status, body, table, method POST/PUT/PATCH, not a chain, not needs_rules; "weak" if no problem found and title lacks "no credentials"/"duplicate"/"does not exist"/"malformed".
4. `coverage` "Every requested category has cases" (warn-level).
5. `matching` "Endpoints matched to a table (field rules known)" (warn-level; endpoints with a body, unmatched, used by cases).
6. `samples` "Existing rows used as values" only if any samples (always passed).
Failure details: `"<n> of <checked>: id1; id2; id3; id4…"`.

##### 9.4 `samples.py`
`read_samples(target, tables) -> (dict, notes)`: only PostgreSQL and MySQL (else `{}`, note "Row sampling is available for PostgreSQL and MySQL only."). `SAMPLE_ROWS=5`. Engine with `_connect_args`; PG `SET TRANSACTION READ ONLY`; for each table `SELECT * FROM <quoted [schema.]table> LIMIT 5` (identifier quoting by the dialect preparer); values normalized (`datetime/date/time` -> ISO, `Decimal` -> float, `UUID` -> str, bytes -> None). Per-table failure -> rollback and note `"<t>: could not read sample rows (<Class>)."`; empty table -> note `"<t>: no existing rows, values from the collection were used."`; connection failure -> overall note. Only the first row of each table is used by the planner (`sample_row`). In `jobs`, the sample notes are appended to `st.adjustments` which makes the report `partial`.

---------------------------------------------------------------------------------------------------

#### 10. `loader.py`

* `BATCH = 500`; `SKIPPABLE = {"23505","23503"}` (unique_violation, foreign_key_violation); `_sqlstate(e)` reads `e.orig.sqlstate`/`pgcode` (or cause).
* `new_steps(boomi)`: eight `LoadStep`s: confirm (React, done), job (FastAPI), recv/batch/adapter/status (Boomi layer, detail note in direct mode), insert (Database), verify (FastAPI).
* `_coerce(sa_type, v)`: converts JSON-ish values to driver types: Uuid -> `uuid.UUID`; JSON str -> `json.loads`; LargeBinary hex -> bytes; Time str -> `time`; Interval "<n> minutes" -> `timedelta`; DateTime str -> `datetime.fromisoformat` (`Z`->`+00:00`); Date str -> `date.fromisoformat(v[:10])`; Numeric -> `Decimal(str(v))`.
* `_pg_text(v)`: renders values as PG text for casts (bool -> true/false; list -> `{"a","b"}` with escaping; dict -> JSON; bytes -> `\x..`; timedelta -> "N seconds"; datetime -> iso).
* `_insert_overriding`: for tables with `GENERATED ALWAYS AS IDENTITY` columns: `INSERT INTO "schema"."table" (cols) OVERRIDING SYSTEM VALUE VALUES (CAST(:p0 AS <compiled type>), ...)` with `_pg_text` parameters (explicit keys so FKs stay valid). Used when any column of the table is in the schema's `identity_always` set.
* **`prepare_keys(eng, target, meta, tables)`** (PostgreSQL only; otherwise identity): for each table in load order reflect it (`autoload_with`, `schema=target.schema`); if it has a single integer PK and rows: in its own transaction get `pg_get_serial_sequence('"schema"."table"', pk)`; if a sequence exists, take `n` values via `SELECT nextval(seq) FROM generate_series(1, n)` and map generated keys (in row order) to the sorted new ids -> `keymap[(table, pk)]`. Then every FK column of this table that references a re-keyed parent (including self references) is rewritten using the parent's map; finally the table's own PK is rewritten. Effect: generated ids never collide with rows already in the target. Non-integer/composite/none PKs untouched.
* **`execute_load(load, tables, target, on_progress, identity_always, ref_cols)`**: engine `create_engine(url, connect_args={"connect_timeout": 10})` (the target's `ssl` setting is NOT passed here). For each table (parents first):
  * reflect table; reflection failure -> failed_batches+1, result row with `error "Table not found in target: <Class>"`, stop.
  * `override` = PG and any table column is identity-always.
  * **Cascade skip**: a row is skipped (counted as `cascade`) when any of its FK values is in `skipped_vals[(parent_table, parent_col)]`; its own referenced-column values are added to `skipped_vals` so its children are skipped too (`ref_cols[table]` = columns other tables reference, built from schema FKs).
  * Remaining rows are coerced (`_coerce` per reflected column type; only columns present in the reflected table) and inserted in batches of 500 each in its own transaction (`conn.execute(tbl.insert(), rows)` or the OVERRIDING variant).
  * On batch error with SQLSTATE not in SKIPPABLE: `failed_batches += 1`, `load.error = "<table>: <first line of cause, <=200 chars>"`, stop the table and the whole load (break). With 23505/23503: retry the chunk row by row in one transaction using SAVEPOINTs (`begin_nested`); clashing rows are counted as skipped and their `ref_cols` values added to `skipped_vals`; any other error in this retry fails the load.
  * After each table: `res.inserted += len(ok_rows)`, `res.skipped += skipped_rows`; if skipped, warning `"<t>: <n> record(s) skipped because they clash with rows already in your database (or depend on a skipped record)."`; stores `(name, ok_rows_original_values)` for verification.
  * **Sequence reset** (PostgreSQL): for each integer PK column with a serial sequence: `SELECT setval(pg_get_serial_sequence(...), GREATEST((SELECT COALESCE(MAX(pk),1) FROM "schema"."table"), (SELECT last_value FROM <seq>)))`.
  * Returns `{"perTable", "inserted", "status": "COMPLETE" if no failedBatches and all tables processed else "ERROR"}`.
* `run_adapter(load, job_id, target_id)`: `get_target(target_id)` (no owner filter); must exist and have `load_allowed` else `PermissionError("Direct load is only enabled for approved PostgreSQL test targets.")`; marks `insert` running; builds `identity_always` map and `ref_cols` from the schema; runs `execute_load`; saves inserted rows in module-level `_STATE[load.id]`; `insert` step done/failed.
* **`verify_load(target, schema_tables, tables, inserted)`** (reads no other data): for each table of the rows actually written: reflect; if no PK, trust adapter counts; else count rows existing for the exact key tuples (chunks of 1000; single-column `IN` or `tuple_ IN`), must equal `len(rows)`; for each FK of the table, left-join to the parent (self-FK uses an alias) and count rows with non-null child value and NULL parent in the same key set; any > 0 -> `fk_valid=False`. Returns `Verification(counts_match, fk_valid)`.
* `finish(load, job_id, target_id)`: step verify running; rows = `_STATE.pop(load.id)` or the full job dataset; `ok = counts_match and fk_valid and no failed_batches`; sets `boomi_status` `COMPLETE/ERROR`, `status` `success/failed`, verify step; audit `load SUCCESS/FAILED`.
* `fail(load, msg)`: status failed, boomi_status ERROR, error, running steps -> failed.
* `run_direct`: marks `job, recv, batch, adapter` done, `run_adapter`, `status` done, `finish`; exception -> `fail`. `_via_boomi`: `run_load_process`; sets `status` step detail `Boomi status: <s>`; non-`COMPLETE`/`SUCCESS` -> `RuntimeError("Boomi reported <status>: <error>")`; else `finish`.
* `start_load(load_id, job_id, target_id, plan_tables)`: builds `LoadJob`, audit REQUESTED, `job` step done, `put_load`; Boomi mode: thread `_via_boomi` and `recv` running; else thread `run_direct`.
* Quirk: `load.warnings`, `per_table` counts and `verification` are updated in place on the stored object, so polling sees progress.

---------------------------------------------------------------------------------------------------

#### 11. Tests (`pytest`, run from backend root; `tests/__init__.py` exists because tests import `tests.test_user_connections`)

**Fixtures** (`conftest.py`): `pg` (session) starts an embedded PostgreSQL via `pgserver.get_server(tempdir)`, creates DB `placement_test_db`, runs `scripts/seed_placement_db.sql`, yields `{host, port, uri}` (user `postgres`, empty password), cleans up. `client` (session): writes a one-target `targets.json` (`pg-placement-test`, loadAllowed true, ssl disable, creds from `T_PG_USER/T_PG_PASS`), sets env (`TARGETS_FILE`, `DATA_DIR`, `API_USERNAME=api_user`, `API_PASSWORD=api_pass-123`, `BOOMI_ENABLED=false`, `OPENAI_API_KEY=""`, `REGISTRY_DB_URL=""`, `MYSQL_HOST=""`), clears settings cache, `TestClient(app)` with `auth=("api_user","api_pass-123")`. `api` fixture (in test_user_connections): per-test SQLite registry file, fresh Fernet key, `ALLOW_PRIVATE_TARGETS=true`, Boomi off, no OpenAI key, credentials set, `registry.init_schema()`, undone afterwards. Headers `H1`/`H2` = distinct `X-Client-Id` values; `body(pg, **kw)` builds a PG connection request.

* `test_e2e.py` (file mode): targets list/connection test (8 tables; evil host rejected with "approved"); schema extraction vs the 8-table DDL (enums from CHECK IN, `hours_worked` check, PK, FKs, serial, unique, nullable, timestamp); one big flow: Fast job (100% FK integrity, 0 unique violations, preview totals), Scenario job (APPROVED covered, REJECTED missing -> `generate-missing` covers all), Mode 3 job from a 2-request Postman collection (no failed checks, 0 records, expected paths), exports of all formats, load refusals (`approved:false` -> 400), load plan, real load into embedded PG with verification and sequence-advance check.
* `test_user_connections.py` (registry mode): own connection saved encrypted and owner-scoped, dedupe reuse, re-test by id; policy/errors (missing client id 400, link-local blocked, error messages leak no usernames, failed attempts not saved, private blocked when disabled); `/internal/metadata` auth/401 and deletion; `/internal/registry/lookup` and `/internal/audit`; Basic auth on all routes and challenge header only on `/internal`; fail-closed 503; PostgreSQL schema selection (`alt` schema, cross-schema FK warning, SQL export schema qualification, schema-name regex rejection); Django-like schema (composite unique, numeric precision, json/array/inet/interval/bytea/uuid/timestamptz, boolean scenario text, loading); completely different "shop" schema (composite PK, identity always, generated column, enum type, self FK, PK-as-FK, no PK, date ordering, identity sequence advance); loading into a database that already contains rows (key re-allocation, 23505 skip with cascade, warnings, verification).
* `test_fuzz_schemas.py`: seeded random-schema generator (`build_schema(seed)`): 5-9 tables per schema `fz<seed>` with PK kinds serial/bigserial/identity/identity_always/uuid/text(16)/composite/none, FKs (nullable, UNIQUE one-to-one, self reference), scalar types list (integer/smallint/bigint/numeric(8,2)/numeric(5,0)/real/double/boolean/varchar(3|12|50|120)/char(3)/text/date/timestamp/timestamptz/time/uuid/jsonb/text[]/integer[]/inet/bytea), CHECK ranges (BETWEEN or >= AND <=) and `IN ('red','green','blue','amber')` lists, UNIQUE, enum type `mood`, generated column `x*2 STORED`, composite UNIQUE, unique indexes (`lower(col)` expression and partial). For `FUZZ_MAX` (default 15) seeds it connects, discovers, generates in Fast mode with random counts (0,3,8,25,60,150), asserts status completed/partial and ZERO failed checks, then loads and asserts success. Property: any schema generates with no failed validation check and loads cleanly.
* `test_testcase_mode.py`: Mode 3 unit/API tests with a "django_celery_beat" style schema and collection: endpoints parsed and matched, token masked, ok status 201; case paths come from the collection; positives pass `run_checks` and negatives each break a rule (`body_problems` exact outputs); sample rows supply parent ids/duplicate values and real rows never targeted by DELETE; Postman/Pytest/XLSX exports valid (Python compiles); API flow (`/api/collection/parse` incl. 422 for bad text, job completes with 0 records, missing collection -> failed job with "Postman collection" error); `read_samples` read-only against embedded PG (empty/missing tables produce notes).
* `test_registry_and_ai.py`: registry encrypts credentials (raw rows contain no plaintext), `get_target` decrypts, `public()` leaks nothing, `match_target`, deactivate; audit trail order; OpenAI blueprint test with monkeypatched `httpx.post`: URL ends `/chat/completions`, model gpt-4o, JSON response_format, key only in header, unknown table dropped, scenario value upper-cased and deduped, enum value-pool rejected, value pool truncated to column length, locale hint applied.

---------------------------------------------------------------------------------------------------

#### 12. Scripts and deployment

* `scripts/dev_demo.py`: starts embedded PG (`pgserver`), creates `placement_test_db` from `seed_placement_db.sql`, writes a temp `targets.json` (pg-placement-test, loadAllowed true, ssl disable), sets `TARGETS_FILE`, `DATA_DIR`, `DEMO_PG_USER=postgres`, `DEMO_PG_PASS=""`, `MYSQL_HOST=""`, `REGISTRY_DB_URL=""` (file mode), default `BOOMI_ENABLED=false`, runs `uvicorn.run("app.main:app", host 127.0.0.1, port 8000)`; cleans PG on exit. (Note: API credentials still required; set `API_USERNAME/API_PASSWORD` in `.env`/environment or every call 503s.)
* `scripts/embedded_pg.py`: throw-away PG as a user DB for use against the real MySQL registry; prints connection details (host/port/db `placement_test_db`/user `postgres`/empty password/SSL disable), requires `ALLOW_PRIVATE_TARGETS=true`.
* `scripts/registry_admin.py` (argparse; loads `.env` via `app.config`): `genkey` (appends a Fernet key to `.env` if `REGISTRY_ENCRYPTION_KEY` not already non-empty there; never prints it), `init` (if `MYSQL_ADMIN_URL` and registry URL set: `CREATE DATABASE IF NOT EXISTS \`<db>\` CHARACTER SET utf8mb4` via an AUTOCOMMIT engine; then `registry.init_schema()`), `add-target --id --label --type {postgresql,mysql,mongodb} --host --port --database [--username] [--password-env NAME | --prompt-password] [--uri-env NAME] [--ssl prefer] [--load-allowed]` (owner "shared", no schema argument), `list` (all rows incl. inactive), `deactivate --id`. Passwords never on the command line.
* `scripts/seed_placement_db.py`: needs `PGADMIN_URL` + `PG_PLACEMENT_PASSWORD` (exits otherwise); creates role (`PG_PLACEMENT_USER` default `atom_app`, string-interpolated password with `'` doubled) and DB `placement_test_db` owned by it if missing, runs the SQL, `GRANT ALL` on tables and sequences in `public`.
* `scripts/seed_placement_db.sql`: eight empty tables: `universities`(SERIAL PK, unique name, `established_year` CHECK BETWEEN 1800 AND 2025), `departments`, `students`(VARCHAR(12) PK, unique email, `enrolment_year >= 2015`, `is_active` default true), `placement_providers`, `supervisors`, `placements`(status IN ACTIVE/COMPLETED/CANCELLED, start/end dates), `timesheets`(`hours_worked` NUMERIC(5,2) CHECK 0..60, status IN SUBMITTED/PENDING/APPROVED/REJECTED/QUERIED, `submitted_at` TIMESTAMP), `timesheet_reviews`(SERIAL PK, decision IN APPROVED/REJECTED/QUERIED). FK chain: universities -> departments -> students; providers -> supervisors; students/providers/supervisors -> placements -> timesheets -> timesheet_reviews.
* **Render**: see 2.4. Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health `/health`. Typical production: MySQL registry (Aiven; CA via `MYSQL_SSL_CA`), `BOOMI_ENABLED=false` unless Render can reach Boomi, `ALLOW_PRIVATE_TARGETS=false`. Local run: `python -m venv .venv`, `pip install -r requirements.txt`, `python scripts\dev_demo.py` (API :8000) or `python -m pytest -q`. Frontend uses `VITE_API_BASE=http://localhost:8000` in `ai_foundry_frontend/.env.local`.
* Registry one-time setup: `registry_admin.py genkey` then `init` (needs MYSQL_* and `MYSQL_SSL_CA`). Users add DBs from the UI (stored encrypted in `registered_targets`, visible only to the browser that saved them via X-Client-Id).

---------------------------------------------------------------------------------------------------

#### 13. Observed inconsistencies, unfinished or surprising items (verbatim notes for rebuilders)

1. README still says Gemini (also `planner.py` docstring) and `X-Internal-Secret` auth; code uses OpenAI and common HTTP Basic. The README `registry_admin.py` commands are corrupted (`scripts\r` / `egistry_admin.py`, unescaped backslash-r) and `boomi_client` docstring cites `/internal/jobs/{job}/batch` and `adapter.py` cites `/internal/mongo/metadata`, neither of which exist.
2. Dead / unused code: `pandas` dependency, `Settings.public_base_url`, `JobState.batch_ref`, `JobState.links` (never populated so preview `links` is always empty), `GenContext.create_chain`, `store.lock`, `registry.purge_audit/recent_audit` (tests only), Blueprint `column_rules` (never consumed by the generator), Boomi-layer `handoff` stages (pure cosmetic: no Boomi call), `_connect_args` sslmode dict mapping is a no-op, `fast`/`scenario` stage `schema`/`graph` do no work other than a 0.2 s sleep.
3. Security/consistency gaps: jobs, loads and previews are not owner-scoped (job id guessing), `/api/plan` and `/api/collection/parse` take raw dicts (KeyError -> 500), loader/verify/sampling connections do not honour the saved `ssl` mode (loader uses libpq default `prefer`; only metadata/credential checks use `_connect_args`), destination policy is checked only at test time (DNS rebinding window), `/internal/*` endpoints ignore ownership by design, `load.execute` raising `PermissionError` returns 403 without failing the load object, `.gitignore` lists `.aiven-ca.pem` but the CA file in the folder is `aiven-ca.pem` (shows as untracked/deleted in git).
4. Persistence caveats: loads are memory-only (restart loses them), failed jobs are not written to disk, `tc_checks` is not persisted (fine because the report holds them), Render's default disk is ephemeral so "restart keeps datasets" depends on `DATA_DIR`; `restore_context` seeds with `(seed or 0) + row count` so generate-missing output is not reproducible with the original seed; `generate_missing` skips repair and passes the raw (uncoerced) scenario string as the forced value.
5. Behavioural quirks: `.env` parser uses `setdefault` (an empty env var beats `.env`); `start_load` blocks only on `load_allowed` (registry_admin can set it for MySQL/Mongo, but the loader only has PostgreSQL-specific paths such as `prepare_keys` skipping and quoting); `normalize` maps every integer width to `integer` only via `udt` (bigint/smallint become `integer` and validation then accepts any Python int, so DB range overflow of smallint is not caught by `_type_ok`); the Mongo path shares the `source="boomi-pymongo"` label while SQL direct mode still reports `boomi-jdbc`; `main.py` still uses deprecated `@app.on_event("startup")`; CORS excludes PUT/PATCH; `Report.uniqueness_violations` is 0 in Mode 3; the `scenario` check can only warn (never fail) so unfulfilled scenarios give status `partial` rather than `failed`.

---

## Prompt 3 - Boomi (built and deployed with the Boomi Companion)

> Copy everything from here to the end of this section into Claude. The Boomi Companion plugin (`bc-integration`) must be installed, and `.env` in the working folder must hold the platform keys listed in the specification (names only; you supply the values).

You are a Boomi integration developer using the **Boomi Companion** skill (`bc-integration:boomi-integration`). Build and deploy the two Boomi processes, the REST connection and operations, the two Web Services Server listener operations and the JSON profiles described below, using the skill's scripts (`boomi-env-check.sh`, `boomi-folder-create.sh`, `boomi-shared-server-info.sh`, `boomi-component-create.sh`, `boomi-component-push.sh`, `boomi-deploy.sh`, `boomi-wss-test.sh`, `boomi-execution-query.sh`). Read the skill's reference files named in the recipe before authoring any XML.

Rules:
- Boomi never connects to a database and never holds database credentials. Both processes only call the Python `/internal/*` API with ids (`targetId`, `jobId`, `loadId`, `requestId`). Do **not** use a Database V2 connector (the runtime has no MySQL JDBC driver) and do not recreate the obsolete MySQL connection, operation or request profile.
- The REST connection `AF FastAPI Internal` uses HTTP Basic (preemptive) with the common username and password. Author the password as empty in the XML and ask the user to type it in the Boomi GUI (never round-trip a pulled REST password; never ask for the plaintext in chat). Make the connection URL the **public HTTPS URL of the deployed API** (for example the Render URL), not `localhost`, whenever the runtime is a cloud attachment; set the connect timeout to 60000 ms so a sleeping API instance can wake.
- The backend must already be running and reachable with its `/internal/*` routes before testing.
- Listener authentication: for a **local atom**, set the Shared Web Server port to Basic and add a user with the common pair. For a **cloud attachment** (for example Singapore Integration Cloud), the listener user is the attachment user shown on the runtime's Shared Web Server page (username is the Attachment Instance ID, shaped like `<accountId>.<suffix>`, with its authentication token as the password). Set `SERVER_BASE_URL`, `SERVER_USERNAME` and `SERVER_TOKEN` on the API accordingly. A 401 on every path, including paths that do not exist, means these perimeter credentials are wrong.

Improvements to apply while rebuilding:
1. Process B must audit the real outcome (`COMPLETE` or `ERROR`) instead of always `RETURNED`.
2. Add a Try/Catch around the REST shapes in both processes so a failed callback writes an `ERROR` audit and returns a clear error document.
3. Leave out the diagnostic "probe" shape that appeared in some recorded executions.
4. Deploy each process once the connection password is set, then redeploy after any dependency change.

Acceptance checks (all must pass):
- `boomi-wss-test.sh --path /ws/simple/executeAfmetadata --data '{"requestId":"t1","targetId":"<registered id>","dbType":"postgresql"}'` returns the metadata JSON and the execution is COMPLETE with audit rows (source `boomi`) in the registry.
- The same call with `"targetId":"nope"` ends in an ERROR execution with the message `Target nope is not registered or is inactive in the registry`.
- `boomi-wss-test.sh --path /ws/simple/executeAfload --data '{"loadId":"L1","jobId":"<job>","targetId":"<id>"}'` returns a status document, and a full load started from the web app shows `Boomi reported COMPLETE` and verified counts.

### Specification (Boomi)

Sources read: `D:\ai_foundry\ai_foundry_backend\active-development\` (process, connector-action, connector-settings, profile.json, .sync-state, feedback/execution-results), the scratchpad helper scripts `build_proc.py`, `build_ops2.py`, `boomi_basic.py` (all three exist), backend `app/boomi_client.py`, `app/routers/internal.py`, `app/config.py` (plus `app/auth.py`, `app/loader.py`, `app/metadata/service.py`, `app/registry.py`, `README.md`, `.env.example`, `render.yaml` for context) and the companion skill `bc-integration:boomi-integration` v1.0.87 (SKILL.md, `references/platform_entities/shared_web_server.md`, `references/guides/api_conversion_patterns.md`, `references/components/rest_connection_component.md`, `web_services_server_start_shape_operation.md`, `scripts/boomi-deploy.sh`).

Secrets are written as `<REDACTED>`. Component GUIDs are abbreviated to 8 chars (rebuild generates new ones; `.sync-state` maps names to ids).

---------------------------------------------------------------------------

#### 1. Purpose and position in the flow

Boomi is the orchestration layer between the Python API and the customer databases. Two Boomi processes, each a Web Services Server (WSS) listener, are called BY the Python API; Boomi then calls back INTO the Python API for everything.

```
React UI --(HTTP Basic, /api/*)--> FastAPI (Python)
   FastAPI --boomi_client._post(): HTTP Basic--> Boomi Shared Web Server
        /ws/simple/executeAfmetadata  (Process A)     /ws/simple/executeAfload (Process B)
   Boomi --REST connector "AF FastAPI Internal" (HTTP Basic)--> FastAPI /internal/*
        (registry/lookup, metadata, batch, load/execute, audit)
   FastAPI --> MySQL registry (Aiven) + customer DBs (PostgreSQL / MongoDB / SQL)   <- only Python touches DBs
```

- Process A "Schema Metadata Extraction": called by `app/metadata/service.py::discover_schema` -> `boomi_client.run_metadata_process` (timeout 90 s).
- Process B "Approved Data Load": called by `app/loader.py::_via_boomi` (background thread) -> `boomi_client.run_load_process` (timeout 600 s).

Rules to preserve:
- **Boomi never touches a database and never holds DB credentials.** Requests carry only ids (`targetId`, `jobId`, `loadId`, `requestId`). Python looks up and decrypts target credentials from its own registry (`boomi_client` docstring: "Requests carry a target id, never credentials").
- **Boomi calls Python /internal APIs** for the registry gate, metadata read, batch reference, insert and audit trail.
- **Why the MySQL database connector was dropped**: the first Process A used a Database V2 connector (connection "AF Registry MySQL (Aiven)" + operation "AF Registry Lookup GET") to query `registered_targets` directly. The first executions (2026-10-26 17:23, 17:24, 17:24 UTC) ended ERROR with message `Failed Loading the class` at the shape "MySQL registry: is target active?" - the JDBC driver class `com.mysql.jdbc.Driver` is not available on the Boomi runtime (no JDBC driver). The lookup became a REST call to Python (`POST /internal/registry/lookup`) returning the same JSON shape the query would have produced (`found`, `db_type`, `load_allowed`). Executions from 17:29 on were COMPLETE.
- Boomi returns Python's raw metadata JSON unchanged; Python normalizes it (`app/metadata/normalize.py`).
- Python modes: `BOOMI_ENABLED=false` = direct mode (Python reads metadata/loads itself; steps note "Boomi not configured"); `BOOMI_ENABLED=true` + `SERVER_BASE_URL` = via Boomi (`boomi_client.configured()`). `/health` reports `boomi: configured|direct-mode`.

---------------------------------------------------------------------------

#### 2. Component inventory

Platform folder: `AtomFoundry-SchemaAndLoad` (README name; XML `folderId="Rjo4OTI5MDE1"`; `.env` key `BOOMI_TARGET_FOLDER`). All components are in this folder, description "built with boomi-companion v1.0.87".

Local layout in `active-development/`: `process/`, `connector-action/` (operations), `connector-settings/` (connections), `profile.json/`, `.sync-state/<type>_<name>.json` (component_id, file_path, content_hash, last_sync), `feedback/execution-results/`.

##### 2.1 Summary

| # | Folder / type | Name | subType | Status |
|---|---|---|---|---|
| 1 | process | AF Process A - Schema Metadata Extraction | - | active (b12f762b) |
| 2 | process | AF Process B - Approved Data Load | - | active (12be9a55) |
| 3 | connector-settings | AF FastAPI Internal | `officialboomi-X3979C-rest-prod` | active (4d945ba5) |
| 4 | connector-action | AF FastAPI POST registry lookup | rest | active (53edc82f) |
| 5 | connector-action | AF FastAPI POST metadata | rest | active (98af1ce2), A only |
| 6 | connector-action | AF FastAPI POST batch | rest | active (5322b865), B only |
| 7 | connector-action | AF FastAPI POST load execute | rest | active (5da88e18), B only |
| 8 | connector-action | AF FastAPI POST audit | rest | active (9fc42a0a), A and B |
| 9 | connector-action | AF WSS Metadata listener | `wss` | active (5a364925) |
| 10 | connector-action | AF WSS Load listener | `wss` | active (b2eb704b) |
| 11 | profile.json | j.AF.Metadata.REQ | - | active (375cdff3) |
| 12 | profile.json | j.AF.Load.REQ | - | active (4e85c872) |
| 13 | profile.json | j.AF.RegistryLookup.RESP | - | active (3ed99940) |
| 14 | profile.json | j.AF.RegistryLookup.REQ | - | UNUSED (db5fbb8a) |
| 15 | connector-settings | AF Registry MySQL (Aiven) | `officialboomi-X3979C-dbv2da-prod` | UNUSED, obsolete (410eb8f5) |
| 16 | connector-action | AF Registry Lookup GET | `officialboomi-X3979C-dbv2da-prod` | UNUSED, obsolete (5545b72d) |

The REST operations have no request/response profile (raw JSON in/out).

##### 2.2 Connection "AF FastAPI Internal" (REST)

`connector-settings`, `subType="officialboomi-X3979C-rest-prod"`, `GenericConnectionConfig`:

| field id | type | value |
|---|---|---|
| url | string | `http://localhost:8000` (FastAPI base URL as seen from the Boomi runtime; operations append `/internal/...`) |
| auth | string | `BASIC` |
| username | string | `<REDACTED>` (= backend `API_USERNAME`; note: the value in the file equals the Boomi account id string, see section 8) |
| password | password | `<REDACTED>` (= backend `API_PASSWORD`) |
| preemptive | boolean | `true` |
| connectTimeout | integer | `10000` ms |
| readTimeout | integer | `600000` ms (sized for the 600 s load call) |
| cookieScope | string | `GLOBAL` |
| enableConnectionPooling | boolean | `false` |

History: originally every operation carried a header `X-Internal-Secret` (built by `build_ops2.py` from `.env` `INTERNAL_SECRET`). `boomi_basic.py` replaced it: sets `auth=BASIC`, inserts `username`/`password`/`preemptive=true` from `.env` `API_USERNAME`/`API_PASSWORD` (XML-escaped plaintext) and strips every `X-Internal-Secret` header from all `AF FastAPI POST *.xml`. Current operations carry only `Content-Type`.

`localhost:8000` only works when the Boomi runtime runs on the same machine as FastAPI (true for all recorded executions, local atom). For a cloud-attached runtime or Render-hosted FastAPI (`render.yaml`, service `atom-foundry-api`) the URL must be the public HTTPS base URL.

##### 2.3 REST operations (`connector-action`, `subType="officialboomi-X3979C-rest-prod"`)

All identical except name and path:

```xml
<Operation returnApplicationErrors="false" trackResponse="false">
  <Archiving directory="" enabled="false"/>
  <Configuration>
    <GenericOperationConfig customOperationType="POST" operationType="EXECUTE">
      <field id="followRedirects" type="string" value="NONE"/>
      <field id="path" type="string" value="<PATH>"/>
      <field id="queryParameters" type="customproperties"><customProperties/></field>
      <field id="requestHeaders" type="customproperties">
        <customProperties><properties key="Content-Type" value="application/json"/></customProperties>
      </field>
      <Options/>
    </GenericOperationConfig>
  </Configuration>
  <Tracking><TrackedFields/></Tracking><Caching/>
</Operation>
```

`returnApplicationErrors="false"`: an HTTP 4xx/5xx from FastAPI fails the connector shape (document error, process ERROR). 2xx bodies flow on as documents.

| Operation | path | Used in | Request JSON | Python response |
|---|---|---|---|---|
| AF FastAPI POST registry lookup | `/internal/registry/lookup` | A shape4, B shape4 | `{"targetId":"<id>"}` | `{"found":1\|0,"db_type":"<type>\|''","load_allowed":1\|0}` |
| AF FastAPI POST metadata | `/internal/metadata` | A shape7 | `{"targetId":"<id>"}` | SQL `{"tables":[...]}`; MongoDB `{"collections":[...]}`; 404 "Unknown or inactive target."; 502 "Metadata read failed: <ExceptionClass>" |
| AF FastAPI POST batch | `/internal/batch` | B shape8 | `{"jobId":"..","loadId":".."}` | `{"batchRef":"<jobId>","tables":[{"table":"t","rows":n}]}` (parents first, no row data); 404 "Unknown job."; side effect: load steps recv/batch done, adapter running |
| AF FastAPI POST load execute | `/internal/load/execute` | B shape10 | `{"loadId":"..","jobId":"..","targetId":".."}` | `{"status":"COMPLETE"\|"ERROR",...,"perTable":[..],"error":<str\|null>}`; 404 "Unknown load."; 403 when target missing / not load_allowed; other exceptions return HTTP 200 `{"status":"ERROR","perTable":[],"error":"<=300 chars"}` |
| AF FastAPI POST audit | `/internal/audit` | A shape16, B shape16 | `{"requestId":"..","processName":"..","status":"..","targetId":".."}` (+ optional `message`) | `{"recorded":true\|false}` (false if registry DB disabled) |

Request models use `CamelModel`, so camelCase is accepted. The lookup response keys are snake_case (`db_type`, `load_allowed`) matching profile `j.AF.RegistryLookup.RESP`. Audit rows are stored with `source='boomi'`.

##### 2.4 WSS listener operations (`connector-action`, `subType="wss"`)

```xml
<Operation><Archiving directory="" enabled="false"/>
 <Configuration>
  <WebServicesServerListenAction inputType="singlejson" objectName="<OBJ>" operationType="EXECUTE"
     outputType="singledata" requestProfile="<REQ profile id>" responseContentType="application/json"/>
 </Configuration><Tracking><TrackedFields/></Tracking><Caching/></Operation>
```

| Operation | objectName | operationType | requestProfile | URL |
|---|---|---|---|---|
| AF WSS Metadata listener | `afmetadata` | EXECUTE | j.AF.Metadata.REQ | `/ws/simple/executeAfmetadata` |
| AF WSS Load listener | `afload` | EXECUTE | j.AF.Load.REQ | `/ws/simple/executeAfload` |

URL = `<SERVER_BASE_URL>/ws/simple/` + lowercase(operationType) + SentenceCase(objectName), no separator. These equal the backend defaults `BOOMI_METADATA_PATH` / `BOOMI_LOAD_PATH`. No responseProfile; `outputType="singledata"` returns the Return Documents document raw.

##### 2.5 JSON profiles (`profile.json`, `JSONProfile strict="false"`)

| Profile | Fields (name : type, key) | Used by |
|---|---|---|
| j.AF.Metadata.REQ | `requestId` character (3), `targetId` character (4), `dbType` character (5) | WSS Metadata listener; Process A Set Properties |
| j.AF.Load.REQ | `loadId` character (3), `jobId` character (4), `targetId` character (5) | WSS Load listener; Process B Set Properties |
| j.AF.RegistryLookup.RESP | `found` number (3, `ProfileNumberFormat numberFormat=""`), `db_type` character (4), `load_allowed` number (5, number format) | decisions in A and B (read from the REST lookup response); the obsolete DB op |
| j.AF.RegistryLookup.REQ | `targetId` character (3) | only the obsolete DB op |

Skeleton: `JSONRootValue key=1 name=Root dataType=character` (DataFormat ProfileCharacterFormat) containing `JSONObject key=2 name=Object isMappable=false`; entries `JSONObjectEntry isMappable=true isNode=true key=N name=..` with `DataFormat`; `<Qualifiers><QualifierList/></Qualifiers>`; `<tagLists/>`. Process shapes reference elements as `elementId="<key>" elementName="<name> (Root/Object/<name>)"`. `dbType` is never captured into a property (Python sends it, Boomi ignores it).

##### 2.6 Unused / obsolete components

- **AF Registry MySQL (Aiven)**: Database V2 connection; `url=jdbc:mysql://<REDACTED host>:16793/aifoundry?sslMode=REQUIRED`, `className=com.mysql.jdbc.Driver`, `username=<REDACTED>`, `password=<REDACTED>` (the local XML holds a clear-text style secret), connectTimeOut 20000, readTimeOut 30000, pooling off.
- **AF Registry Lookup GET**: Database V2 op, `customOperationType="GET"`, `operationType="EXECUTE"`, `objectTypeId="registered_targets"`, `GetType="Standard Get"`, requestProfile j.AF.RegistryLookup.REQ, responseProfile j.AF.RegistryLookup.RESP, `returnApplicationErrors="true"`, SQL `select count(*) as found, coalesce(max(db_type),'') as db_type, coalesce(max(load_allowed),0) as load_allowed from registered_targets where id = $targetId and active = 1`.
- **j.AF.RegistryLookup.REQ**.
Neither process references them. Do NOT recreate; they can be deleted.

---------------------------------------------------------------------------

#### 3. Processes

Common attributes: `allowSimultaneous="true" enableUserLog="false" processLogOnErrorOnly="false" purgeDataImmediately="false" stopProcessingIfZeroDocuments="true" updateRunDates="false" workload="general"`; `<bns:processOverrides/>`; empty description. Layout: x = 48 + 225*i, y = 48 (alternate row y=208/216 for false/return paths). Dragpoint coordinates = destination x-16, y+8. REST steps: `connectorType="officialboomi-X3979C-rest-prod" actionType="SEND" allowDynamicCredentials="NONE" hideSettings="false"`, `connectionId` = AF FastAPI Internal, `operationId` per op. Message shapes `combined="false"` and use the JSON quote-toggle idiom `'{"k":"'{1}'"}'`. Set Properties: `shapetype="documentproperties"`, each property `name="Dynamic Process Property - <DPP>" propertyId="process.<DPP>" persist="false" shouldEncrypt="false" defaultValue=""`, source `valueType="profile"` -> `profileelement` of the listener request profile (`profileType="profile.json"`). Process-property parameter in Message/Exception: `<parametervalue key="n" valueType="process"><processparameter processproperty="<DPP>" processpropertydefaultvalue=""/>`.

##### 3.1 Process A - "AF Process A - Schema Metadata Extraction"

Trigger: POST `/ws/simple/executeAfmetadata`, body `{"requestId":"<12 hex>","targetId":"<registered target id>","dbType":"postgresql|mongodb|..."}` (Python: `uuid4().hex[:12]`).

| Shape | Type | Label | Configuration | Next |
|---|---|---|---|---|
| shape1 | start | WSS listener: executeAfmetadata | connectoraction `actionType="Listen" connectorType="wss" hideSettings="true"`, operationId = AF WSS Metadata listener, no connection | shape2 |
| shape2 | Set Properties | Capture target and request id | DPP_TARGET_ID <- Metadata.REQ elementId 4 `targetId`; DPP_REQUEST_ID <- elementId 3 `requestId` | shape3 |
| shape3 | message | Build registry lookup input | `'{"targetId":"'{1}'"}'`, {1}=DPP_TARGET_ID | shape4 |
| shape4 | REST | Registry lookup (MySQL via Python) | op registry lookup | shape5 |
| shape5 | decision | Target registered and active | `comparison="greaterthan"`; value1 profile RESP elementId 3 `found (Root/Object/found)`; value2 static `0` | True -> shape6; False -> shape9 |
| shape6 | message | Build FastAPI request (target id only) | `'{"targetId":"'{1}'"}'`, DPP_TARGET_ID | shape7 |
| shape7 | REST | Python adapter reads metadata | op metadata | shape14 |
| shape14 | branch | Audit then return | `numBranches="2"`; dragpoint identifier 1 -> shape15; identifier 2 -> shape8 | - |
| shape15 | message (branch 1) | Build audit record | `'{"requestId":"'{1}'","processName":"A-metadata","status":"COMPLETE","targetId":"'{2}'"}'`; {1}=DPP_REQUEST_ID, {2}=DPP_TARGET_ID | shape16 |
| shape16 | REST | Write audit (MySQL via Python) | op audit | shape17 |
| shape17 | stop | (none) | `continue="true"` | - |
| shape8 | returndocuments (branch 2) | (none) | `<returndocuments/>`: returns the metadata response document to the WSS caller | - |
| shape9 | exception (False path) | Target not registered | `stopProcessReturnSingleDoc="false" stopsingledoc="true" title="Target not registered"`, message `Target {1} is not registered or is inactive in the registry`, {1}=DPP_TARGET_ID (`usesEncryption="false"`) | - |

Branch path 1 (audit) runs to completion before path 2 (return). No Try/Catch: any REST failure (e.g. Python 502 on metadata) fails the document; Python sees `BoomiError("Boomi returned HTTP ...")` and writes its own audit FAILED.
Success response to Python: raw `/internal/metadata` JSON. Observed negative test: target `nope` -> execution ERROR `Target nope is not registered or is inactive in the registry` (decision log: `compareType=GREATERTHAN firstValue=0 secondValue=0`, false).

##### 3.2 Process B - "AF Process B - Approved Data Load"

Trigger: POST `/ws/simple/executeAfload`, body `{"loadId":"..","jobId":"..","targetId":".."}`.

| Shape | Type | Label | Configuration | Next |
|---|---|---|---|---|
| shape1 | start | WSS listener: executeAfload | Listen, op AF WSS Load listener | shape2 |
| shape2 | Set Properties | Capture load, job and target ids | DPP_LOAD_ID <- Load.REQ elementId 3 `loadId`; DPP_JOB_ID <- 4 `jobId`; DPP_TARGET_ID <- 5 `targetId` | shape3 |
| shape3 | message | Build registry lookup input | `'{"targetId":"'{1}'"}'` | shape4 |
| shape4 | REST | Registry lookup (MySQL via Python) | op registry lookup | shape5 |
| shape5 | decision | Target registered and active | `greaterthan`, RESP `found` vs static `0` | True -> shape6; False -> shape12 |
| shape6 | decision | Loading allowed for target | `comparison="equals"`; RESP elementId 5 `load_allowed (Root/Object/load_allowed)` vs static `1` | True -> shape7; False -> shape13 |
| shape7 | message | Build batch reference request | `'{"jobId":"'{1}'","loadId":"'{2}'"}'`; {1}=DPP_JOB_ID, {2}=DPP_LOAD_ID | shape8 |
| shape8 | REST | Retrieve batch reference | op batch (its response is discarded by the next Message; call is for Python-side step tracking) | shape9 |
| shape9 | message | Build load request | `'{"loadId":"'{1}'","jobId":"'{2}'","targetId":"'{3}'"}'`; {1}=DPP_LOAD_ID, {2}=DPP_JOB_ID, {3}=DPP_TARGET_ID | shape10 |
| shape10 | REST | Python adapter inserts parents first | op load execute | shape14 |
| shape14 | branch | Audit then return | 2 branches: 1 -> shape15; 2 -> shape11 | - |
| shape15 | message | Build audit record | `'{"requestId":"'{1}'","processName":"B-load","status":"RETURNED","targetId":"'{2}'"}'`; {1}=DPP_LOAD_ID (used as requestId), {2}=DPP_TARGET_ID | shape16 |
| shape16 | REST | Write audit (MySQL via Python) | op audit | shape17 |
| shape17 | stop | (none) | `continue="true"` | - |
| shape11 | returndocuments | (none) | returns `{"status":..,"perTable":[..],"error":..}` | - |
| shape12 | exception | Target not registered | same text as in A | - |
| shape13 | exception | Loading not allowed | title "Loading not allowed", message `Loading is not enabled for target {1}`, {1}=DPP_TARGET_ID | - |

Python after B returns (`loader._via_boomi`): `status` must be `COMPLETE` or `SUCCESS`, else `Boomi reported <status>: <error>` -> `loader.fail`; then `loader.finish` verifies counts/FKs and writes its own audit rows (SUCCESS/FAILED).

Status vocabulary: Boomi audit `status` = `COMPLETE` (A) / `RETURNED` (B, always, even if the load returned ERROR with HTTP 200); processName `A-metadata` / `B-load`. Load execute status `COMPLETE` | `ERROR`. Execution records: STARTED, COMPLETE, ERROR (`executionType: exec_listener`). Exception titles: "Target not registered", "Loading not allowed". Python-side audit statuses: REQUESTED, COMPLETE, FAILED, SUCCESS (`source='python'`).

---------------------------------------------------------------------------

#### 4. Authentication model

Two independent HTTP Basic hops with one "common" credential pair idea (React, Boomi and FastAPI share `API_USERNAME`/`API_PASSWORD`).

1. **FastAPI -> Boomi listener** (`boomi_client._post`): `SERVER_AUTH_TYPE` (default `basic`). If not `bearer` and a username exists, httpx sends Basic with `SERVER_USERNAME`/`SERVER_TOKEN`, each falling back to `API_USERNAME`/`API_PASSWORD` when empty. If `bearer`: `Authorization: Bearer <SERVER_BEARER_TOKEN>`. `SERVER_VERIFY_SSL=false` disables TLS verification. Code comment: a listener port set to "none" ignores the credentials.
   - Listener auth is not on the process; it is set per port of the runtime's **Shared Web Server** (README: set authentication type Basic and add a user with the common credentials).
   - **Cloud attachment** (e.g. "Singapore Integration Cloud"): the Atom Cloud enforces its own perimeter Basic auth independent of the atom's `minAuth`. The perimeter user is the cloud-attachment user (Manage -> Cloud Management -> <cloud> -> Users, shaped like `bc@<account>.<atom token>`), NOT the platform API user (`BOOMI_USERNAME`/`BOOMI_API_TOKEN`). Set `SERVER_AUTH_TYPE=basic`, `SERVER_USERNAME`/`SERVER_TOKEN` = attachment user and its credential (<REDACTED>), `SERVER_BASE_URL` = cloud HTTPS base URL. If that pair differs from the common pair it must be set explicitly (otherwise the fallback sends the common pair).
   - **401 symptoms**: HTTP 401 from the cloud URL for every path including nonexistent ones, even when `SharedServerInformation.minAuth=none` = cloud-perimeter signature (not route registration). Python raises `BoomiError("Boomi returned HTTP 401: ...")`. `boomi-deploy.sh` detects it (baseline probe of `/ws/simple/_bcCollisionBaseline_*` returns 401 and it skips the collision check, blaming SERVER_USERNAME/SERVER_TOKEN). Other symptoms: 404 on `/ws/simple/...` = not deployed / wrong objectName / `apiType=advanced` (bare WSS routes not registered; needs an API Service Component); `BoomiError("Boomi is unreachable ...")` = network/TLS.
2. **Boomi -> FastAPI /internal/\***: REST connection `auth=BASIC`, `preemptive=true`, username/password = `API_USERNAME`/`API_PASSWORD`. FastAPI `require_basic` (router dependency for `/internal`): 503 if the API credentials are unset (fail closed); 401 with `WWW-Authenticate: Basic realm="atom-foundry"` for missing/invalid credentials (constant-time compare); only `/health` is open. Symptom of a bad connection password: the first REST shape (Registry lookup) errors with HTTP 401 and the process ends ERROR.
   - The REST password is write-only in Boomi. A pulled connection holds a reference token, not the password, and re-pushing a pulled REST connection silently breaks auth (skill Issue #39; push succeeds, 401 at runtime). Never push the local XML again; re-enter the password in the Boomi GUI (or use an Environment Extension on `GenericConnectionConfig/field[@id='password']/@value`).
3. Legacy, removed: header `X-Internal-Secret` / env `INTERNAL_SECRET`. Backend README still mentions it (stale).

---------------------------------------------------------------------------

#### 5. Deployment

- **Packaging/deploy**: only the two processes are deployed. `boomi-deploy.sh <process xml>` packages (PackagedComponent) then deploys (DeployedPackage) to `BOOMI_ENVIRONMENT_ID`, replacing any existing deployment of that process in that environment. Connections, operations, profiles are bundled as dependencies (created/pushed, not deployed separately). Redeploy the process after changing any dependency.
- **Environment/attachment**: recorded executions ran on a local atom (`atom_intelligence_local`, id in `.env` as `BOOMI_TEST_ATOM_ID`) attached to the environment; `.env` `SERVER_BASE_URL` is a local address. For the cloud attachment "Singapore Integration Cloud": attach the environment to the cloud, deploy both processes to that environment, set `SERVER_BASE_URL` to the cloud base URL plus perimeter credentials (section 4), and make the REST connection `url` a public URL reachable from the cloud (not `localhost`).
- **Listener URL**: `${SERVER_BASE_URL}/ws/simple/executeAfmetadata` and `.../executeAfload` (must be unique on the runtime; deploy script warns on collision).
- **API tier**: run `boomi-shared-server-info.sh`; bare WSS listeners are valid for `apiType=basic|intermediate`.
- **Env keys (names only)**
  - Companion `.env` (`D:\ai_foundry\ai_foundry_backend\.env`, gitignored; `active-development/` also gitignored): `BOOMI_API_URL`, `BOOMI_USERNAME`, `BOOMI_API_TOKEN`, `BOOMI_ACCOUNT_ID`, `BOOMI_VERIFY_SSL`, `BOOMI_TARGET_FOLDER`, `BOOMI_ENVIRONMENT_ID`, `BOOMI_TEST_ATOM_ID` (`BOOMI_COMPANION_LOG_ACTIVITY` present commented out).
  - Shared web server (companion `boomi-wss-test.sh`, deploy collision check, and FastAPI `config.py`): `SERVER_BASE_URL`, `SERVER_AUTH_TYPE`, `SERVER_USERNAME`, `SERVER_TOKEN`, `SERVER_BEARER_TOKEN`, `SERVER_VERIFY_SSL`.
  - FastAPI-only: `BOOMI_ENABLED`, `BOOMI_METADATA_PATH` (default `/ws/simple/executeAfmetadata`), `BOOMI_LOAD_PATH` (default `/ws/simple/executeAfload`), `PUBLIC_BASE_URL` (documentation only).
  - Common credentials: `API_USERNAME`, `API_PASSWORD`.
  - Context: `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE`, `MYSQL_SSL_CA`, `REGISTRY_DB_URL`, `REGISTRY_ENCRYPTION_KEY`, `OPENAI_*`, `CORS_ORIGINS`, `ALLOW_PRIVATE_TARGETS`.
  - Name clash: `BOOMI_VERIFY_SSL` (platform API) vs `SERVER_VERIFY_SSL` (listener / FastAPI).

---------------------------------------------------------------------------

#### 6. Execution evidence (feedback/execution-results)

UTC, 2026-10-26 (account/atom/execution ids omitted):
1. 17:23:05, 17:24:13, 17:24:22 - Process A ERROR `Failed Loading the class` at DB shape "MySQL registry: is target active?" (log: "Shape executed with errors ... No documents found. Skipping execution for the Target registered and active step").
2. 17:29:26-17:29:41 A COMPLETE (3 outbound docs); 17:29:44 B COMPLETE (4 outbound docs); 17:29:57 B ERROR for target `nope`; 17:43:54 and 17:43:57 A COMPLETE; 17:44:01 B COMPLETE.
3. 18:12:38 and 18:13:52 - A ERROR for target `nope` (expected negative test). These runs show an extra Notify "probe" shape (`PROBE auth=[] hdr=[] ua=[]`) after Set Properties, used to inspect the inbound Authorization header; it is not in the current local XML.
Durations about 0.4-1.8 s per run. Success outbound counts: A = 3, B = 4.

---------------------------------------------------------------------------

#### 7. Rebuild recipe (companion skill steps, in order)

Resolve `<skill-path>` = `%USERPROFILE%\.claude\plugins\cache\boomi-companion\bc-integration\1.0.87\skills\boomi-integration`; run scripts from `D:\ai_foundry\ai_foundry_backend` (where `.env` and `active-development/` live) with absolute script paths. Before building read `BOOMI_THINKING.md`, then `components/process_component.md`, `rest_connection_component.md`, `rest_connector_operation_component.md`, `web_services_server_start_shape_operation.md`, `json_profile_component.md`, `steps/start_step.md`, `set_properties_step.md`, `message_step.md`, `rest_connector_step.md`, `decision_step.md`, `branch_step.md`, `exception_step.md`, `return_documents_step.md`, `stop_step.md`, `guides/parameter_value_types.md`, `process_testing_guide.md`, `api_conversion_patterns.md`, `platform_entities/shared_web_server.md`.

1. `bash <skill-path>/scripts/boomi-env-check.sh`; `boomi-folder-create.sh --test-connection`. On failure use `/bc-integration:env-setup-guide`.
2. `bash <skill-path>/scripts/boomi-shared-server-info.sh`: confirm `apiType` basic/intermediate. Ask the user which port/auth the listener uses (local: None or Basic; cloud attachment: Basic with the attachment user). Set `SERVER_BASE_URL`, `SERVER_AUTH_TYPE` and, if different from the common pair, `SERVER_USERNAME`/`SERVER_TOKEN`.
3. `bash <skill-path>/scripts/boomi-folder-create.sh "AtomFoundry-SchemaAndLoad"` (or reuse `BOOMI_TARGET_FOLDER`); use its id as `folderId` everywhere.
4. Profiles (`mkdir -p active-development/profile.json`, empty `componentId`, `boomi-component-create.sh` each): `j.AF.Metadata.REQ` (requestId, targetId, dbType), `j.AF.Load.REQ` (loadId, jobId, targetId), `j.AF.RegistryLookup.RESP` (found number, db_type character, load_allowed number). Keep keys 3,4,5 in that order. Do not create RegistryLookup.REQ.
5. Connection `AF FastAPI Internal` (`connector-settings`, REST subType) per 2.2 with `password` authored as `value=""`; create it, then ask the user to type the password in the Boomi GUI (skill: never round-trip a pulled REST password; do not request the plaintext). Prefer reusing an existing connection via the skill's connection discovery. (The original build instead wrote plaintext from `.env` through `boomi_basic.py`; that only works on the first create/push.)
6. Five REST operations (2.3 template; paths `/internal/registry/lookup`, `/internal/metadata`, `/internal/batch`, `/internal/load/execute`, `/internal/audit`; only `Content-Type` header). `boomi-component-create.sh` each.
7. Two WSS operations (2.4): `afmetadata` + Metadata.REQ, `afload` + Load.REQ, `EXECUTE`, `singlejson` in, `singledata` out, `application/json`.
8. Read ids from `.sync-state/*.json` (`component_id`), render both processes per section 3 (pattern of `build_proc.py`: `cid(name)` glob lookup, helpers for dragpoints, Set Properties, Message, decision, exception), create (empty `componentId`) then update via `boomi-component-push.sh`. Use `shapetype="documentproperties"`, start `actionType="Listen" connectorType="wss"`, `<stop continue="true"/>` for the audit tail, `<returndocuments/>` for the return branch. Optionally run the `boomi-canvas-arranger` agent.
9. Backend `.env`: `BOOMI_ENABLED=true`, `SERVER_BASE_URL`, auth keys; restart FastAPI (path defaults already match).
10. Deploy each process: `bash <skill-path>/scripts/boomi-deploy.sh "active-development/process/AF Process A - Schema Metadata Extraction.xml"` and the same for B (needs `BOOMI_ENVIRONMENT_ID`; replaces existing deployments, confirm with the user if redeploying). Wait 10-15 s.
11. Test: `boomi-wss-test.sh --path /ws/simple/executeAfmetadata --data '{"requestId":"t1","targetId":"<registered id>","dbType":"postgresql"}'`; `--path /ws/simple/executeAfload --data '{"loadId":"L1","jobId":"<job>","targetId":"<id>"}'`; negative test `targetId":"nope"` must give execution ERROR "Target nope is not registered or is inactive in the registry". Inspect with `boomi-execution-query.sh --process-id <id> --limit 3` and `--execution-id <id> --logs`.
12. Troubleshoot: 401 on every path = cloud perimeter credentials; 401 at the REST shape = connection password; 404 = not deployed / objectName / apiType; "Failed Loading the class" = a Database connector snuck in (use REST via Python).
13. Do not use Database V2; do not recreate the obsolete MySQL connection/operation/REQ profile.

---------------------------------------------------------------------------

#### 8. Inconsistencies and open points

- Obsolete DB components still exist locally and on the platform; the local MySQL connection XML contains a clear-text style DB password.
- Process B audits `RETURNED` regardless of load result; Process A audits `COMPLETE`; no Try/Catch, so REST failures end the listener with an error and no Boomi `ERROR` audit.
- The 18:12/18:13 executions contain a "probe" Notify not present in the local XML; sync-state timestamps (A 18:13:27, B 17:28:36) suggest the deployed version may differ from the local file.
- Backend README still says `X-Internal-Secret`; real auth is HTTP Basic.
- REST connection `url` is `http://localhost:8000` and `SERVER_BASE_URL` is local: valid only for the local atom, not for the Singapore cloud attachment or a Render-hosted API.
- The REST connection `username` value equals the Boomi account id string and its stored password has a UUID-like form rather than the 128-hex reference the skill describes; it is unclear whether API_USERNAME/API_PASSWORD are really the common pair (not verified, values not copied).

---

## End-to-end check after all three parts are built

1. Backend: `pytest -q` passes; `/health` reports `boomi: configured` and `ai: openai` (or `rules-only` without a key).
2. Boomi: both processes deployed; direct `boomi-wss-test.sh` calls succeed and the negative test fails as specified.
3. Frontend: sign in with the common credentials; connect a disposable PostgreSQL database; extract the schema (Boomi Process A stage shown); run Mode 1, Mode 2 with a scenario description, and Mode 3 with a Postman collection; preview, export and (Modes 1 and 2) approve a load and see verified counts.
4. Deploy: Render (API), Vercel (`VITE_API_BASE` set before the build; the API's `CORS_ORIGINS` set to the Vercel origin), Boomi connection URL set to the Render URL.
