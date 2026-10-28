// src/api/mock/mockApi.ts
import type {
  Blueprint,
  ConnectionRequest,
  Job,
  LoadJob,
  Report,
  Row,
  Schema,
  ScenarioCoverage,
  TestCase,
  TestCaseCoverage,
  TestCategory,
} from '../../types'
import type { Api } from '../types'
import { parseOpenApi } from '../../lib/openapi'
import { planBlueprint, planTestCases } from './ai'
import { dependencyOrder, GenContext, requiredParents, type Dataset } from './engine'
import { buildExport } from './exporters'
import { APPROVED_TARGETS, buildSchema } from './schemas'
import { scenarioCoverage, unsupportedConstraints, validate } from './validator'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

interface JobCtx {
  job: Job
  schema: Schema
  ctx?: GenContext
  dataset: Dataset
  order: string[]
  links: Record<string, Record<string, string[]>>
  coverage?: ScenarioCoverage[]
  adjustments: string[]
  unsupported: string[]
  requested: Record<string, number>
  started: number
  apiBaseUrl?: string
  hasSpec: boolean
}

const jobs = new Map<string, JobCtx>()
const loads = new Map<string, LoadJob & { ctxId: string; t0: number; plan: { table: string; expected: number }[] }>()
let seq = 0

const STAGES: Record<string, { id: string; label: string; layer: string }[]> = {
  fast: [
    { id: 'handoff', label: 'Record generation-job handoff', layer: 'Boomi' },
    { id: 'schema', label: 'Validate normalized schema', layer: 'Python' },
    { id: 'graph', label: 'Build dependency graph (parents first)', layer: 'Python' },
    { id: 'rows', label: 'Generate parent then child records', layer: 'Python' },
    { id: 'validate', label: 'Run nine validation checks', layer: 'Python' },
    { id: 'store', label: 'Store dataset for paginated preview', layer: 'Python' },
  ],
  scenario: [
    { id: 'handoff', label: 'Supply metadata and job context', layer: 'Boomi' },
    { id: 'ai', label: 'AI builds the generation blueprint', layer: 'AI' },
    { id: 'bp', label: 'Validate blueprint against schema (Pydantic)', layer: 'Python' },
    { id: 'graph', label: 'Build dependency graph (parents first)', layer: 'Python' },
    { id: 'rows', label: 'Generate interconnected records', layer: 'Python' },
    { id: 'scenarios', label: 'Apply scenario rules and verify counts', layer: 'Python' },
    { id: 'validate', label: 'Run nine validation checks', layer: 'Python' },
    { id: 'store', label: 'Store dataset for paginated preview', layer: 'Python' },
  ],
  testcase: [
    { id: 'handoff', label: 'Supply metadata and job context', layer: 'Boomi' },
    { id: 'ai', label: 'AI proposes test-case plan', layer: 'AI' },
    { id: 'spec', label: 'Validate specifications against schema', layer: 'Python' },
    { id: 'prereq', label: 'Generate prerequisite records, parents first', layer: 'Python' },
    { id: 'manifest', label: 'Build test-case manifest', layer: 'Python' },
    { id: 'validate', label: 'Run nine validation checks', layer: 'Python' },
    { id: 'store', label: 'Store dataset for paginated preview', layer: 'Python' },
  ],
}

function matchTarget(req: ConnectionRequest) {
  if (req.targetId) return APPROVED_TARGETS.find((t) => t.id === req.targetId)
  if (req.dbType === 'mongodb') {
    const m = req.uri?.match(/mongodb(?:\+srv)?:\/\/(?:[^@/]+@)?([^/:?]+)(?::(\d+))?\/([^?]+)?/i)
    if (!m) return undefined
    return APPROVED_TARGETS.find((t) => t.dbType === 'mongodb' && t.host === m[1] && (!m[3] || t.database === m[3]))
  }
  return APPROVED_TARGETS.find((t) => t.dbType === req.dbType && t.host === req.host?.trim() && t.port === req.port && t.database === req.database?.trim())
}

function nineChecks(c: JobCtx) {
  return validate({ schema: c.schema, dataset: c.dataset, coverage: c.coverage, testCases: c.job.testCases })
}

function buildReport(c: JobCtx): Report {
  const checks = nineChecks(c)
  const byId = Object.fromEntries(checks.map((k) => [k.id, k]))
  const pct = (id: string) => {
    const k = byId[id]
    return k && k.checked ? Math.round(((k.checked - k.failed) / k.checked) * 1000) / 10 : 100
  }
  const perTable = Object.entries(c.dataset).map(([table, rows]) => ({ table, requested: c.requested[table] ?? rows.length, generated: rows.length }))
  const failed = checks.some((k) => k.status === 'failed')
  const warn = checks.some((k) => k.status === 'warning') || c.adjustments.length > 0
  const tc = c.job.testCases
  const testCoverage: TestCaseCoverage | undefined = tc && {
    byCategory: (['positive', 'negative', 'boundary', 'workflow'] as TestCategory[]).reduce((a, k) => ({ ...a, [k]: tc.filter((t) => t.category === k).length }), {} as Record<TestCategory, number>),
    total: tc.length,
    withPrerequisites: tc.filter((t) => t.prerequisiteRecords.length).length,
    readyToExport: tc.filter((t) => t.ready).length,
    needingRules: tc.filter((t) => t.needsRules && !t.ready).length,
  }
  return {
    jobId: c.job.id,
    dbType: c.schema.dbType,
    database: c.schema.database,
    tablesDiscovered: c.schema.tables.length,
    mode: c.job.config.mode,
    recordsRequested: perTable.reduce((s, t) => s + t.requested, 0),
    recordsGenerated: perTable.reduce((s, t) => s + t.generated, 0),
    dataTypeValidity: pct('type'),
    relationshipIntegrity: pct('fk'),
    uniquenessViolations: (byId.unique?.failed ?? 0) + (byId.pk?.failed ?? 0),
    status: failed ? 'failed' : warn ? 'partial' : 'completed',
    durationMs: Math.round(performance.now() - c.started),
    unsupportedConstraints: c.unsupported,
    adjustments: c.adjustments,
    checks,
    perTable,
    scenarioCoverage: c.coverage,
    testCoverage,
  }
}

function generateTables(c: JobCtx, counts: { table: string; count: number }[], blueprint?: Blueprint) {
  const { schema } = c
  const ctx = new GenContext(schema, blueprint?.localeHint ?? c.job.config.locale, c.job.config.seed, blueprint?.domain ?? c.job.config.description)
  c.ctx = ctx
  const want = new Map(counts.filter((t) => t.count > 0).map((t) => [t.table, t.count]))
  const selected = new Set(want.keys())
  for (const p of requiredParents(schema, selected)) {
    want.set(p, 5)
    c.adjustments.push(`Added parent table "${p}" with 5 records because a selected table has a required foreign key to it.`)
  }
  for (const [k, v] of want) c.requested[k] = counts.find((t) => t.table === k)?.count ?? v
  const { order, cyclic, selfRefs } = dependencyOrder(schema.tables, selected)
  for (const t of cyclic) c.unsupported.push(`${t}: part of a cyclic relationship. Skipped instead of bypassing constraints.`)
  for (const t of new Set(selfRefs)) c.unsupported.push(`${t}: self-reference handled by leaving the first record's parent null.`)
  c.order = order

  // Feasibility: unique columns limited by enum size or by a 1:1 parent
  for (const name of order) {
    const t = schema.tables.find((x) => x.name === name)!
    let n = want.get(name)!
    for (const col of t.columns) {
      if (col.unique && !col.primaryKey && col.enumValues && n > col.enumValues.length) {
        c.adjustments.push(`${name}: ${n} records impossible, unique column "${col.name}" only has ${col.enumValues.length} permitted values. Proposed ${col.enumValues.length}.`)
        n = col.enumValues.length
      }
      const fk = t.foreignKeys.find((f) => f.column === col.name)
      if (col.unique && fk && !col.primaryKey && (want.get(fk.refTable) ?? 0) < n) {
        c.adjustments.push(`${name}: unique foreign key "${col.name}" needs ${n} distinct ${fk.refTable} records, only ${want.get(fk.refTable) ?? 0} exist. Proposed ${want.get(fk.refTable) ?? 0}.`)
        n = want.get(fk.refTable) ?? 0
      }
    }
    want.set(name, n)
  }

  // Scenario slot allocation
  const forcedBy: Record<string, Row[]> = {}
  for (const name of order) forcedBy[name] = Array.from({ length: want.get(name)! }, () => ({}))
  const byCol = new Map<string, { table: string; column: string; items: { value: string; count: number }[] }>()
  for (const s of blueprint?.scenarios ?? []) {
    const col = schema.tables.find((t) => t.name === s.table)?.columns.find((x) => x.name === s.column)
    if (!want.has(s.table) || !col || (col.enumValues && !col.enumValues.includes(s.value))) continue
    const k = `${s.table}.${s.column}`
    if (!byCol.has(k)) byCol.set(k, { table: s.table, column: s.column, items: [] })
    byCol.get(k)!.items.push({ value: s.value, count: s.count })
  }
  for (const g of byCol.values()) {
    const slots = ctx.faker.helpers.shuffle(forcedBy[g.table].map((_, i) => i))
    let cursor = 0
    for (const it of g.items) for (let i = 0; i < it.count && cursor < slots.length; i++) forcedBy[g.table][slots[cursor++]][g.column] = it.value
    const col = schema.tables.find((t) => t.name === g.table)!.columns.find((x) => x.name === g.column)!
    const others = (col.enumValues ?? []).filter((v) => !g.items.some((i) => i.value === v))
    const pool = others.length ? others : (col.enumValues ?? [])
    if (pool.length) for (const f of forcedBy[g.table]) if (!(g.column in f)) f[g.column] = ctx.faker.helpers.arrayElement(pool)
  }

  for (const name of order) {
    const t = schema.tables.find((x) => x.name === name)!
    for (const forced of forcedBy[name]) {
      if (t.foreignKeys.some((f) => f.refTable === name) && !ctx.dataset[name]?.length) {
        const selfFk = t.foreignKeys.find((f) => f.refTable === name)!
        ctx.addRow(name, { [selfFk.column]: null, ...forced })
      } else ctx.addRow(name, forced)
    }
    ctx.dataset[name] ??= []
  }
  c.dataset = ctx.dataset
}

function generateTestCases(c: JobCtx) {
  const cfg = c.job.config.testCase!
  const ctx = new GenContext(c.schema, c.job.config.locale, c.job.config.seed, cfg.feature)
  c.ctx = ctx
  let endpoint: { method: string; path: string } | undefined
  if (cfg.openApiText) {
    try {
      const spec = parseOpenApi(cfg.openApiText)
      c.hasSpec = true
      c.apiBaseUrl = cfg.apiBaseUrl || spec.baseUrl
      const chosen = spec.endpoints.filter((e) => !cfg.selectedEndpoints?.length || cfg.selectedEndpoints.includes(`${e.method} ${e.path}`))
      endpoint = chosen.find((e) => e.method === 'POST') ?? chosen[0]
    } catch (e) {
      c.adjustments.push(`OpenAPI specification ignored: ${(e as Error).message}`)
    }
  } else c.apiBaseUrl = cfg.apiBaseUrl
  const { cases, target } = planTestCases(c.schema, cfg.feature, cfg.categories, ctx, endpoint)
  const rulesSupplied = c.hasSpec || !!cfg.businessRules?.trim()
  c.order = dependencyOrder(c.schema.tables, new Set(c.schema.tables.map((t) => t.name))).order
  const out: TestCase[] = []
  for (const pc of cases) {
    const created: { table: string; key: string }[] = []
    if (pc.prereq.kind === 'parents') {
      const row = ctx.createChain(target.name, {}, 3, created)
      ctx.dataset[target.name].pop()
      created.pop()
      ctx.counters[target.name]--
      if (pc.fixture)
        for (const f of target.foreignKeys) if (f.column in pc.fixture.body! && pc.fixture.body![f.column] === null) pc.fixture.body![f.column] = row[f.column]
    } else if (pc.prereq.kind === 'row') {
      const row = ctx.createChain(target.name, pc.prereq.forced, 3, created)
      if (pc.fixture) pc.fixture.path = pc.fixture.path.replace('{id}', ctx.pkOf(target.name, row))
      for (const cr of created) {
        const rec = ctx.dataset[cr.table].find((r) => ctx.pkOf(cr.table, r) === cr.key)
        if (rec && 'is_authorized' in rec) rec.is_authorized = true
      }
    }
    for (const cr of created) ((c.links[cr.table] ??= {})[cr.key] ??= []).push(pc.id)
    const { prereq: _p, ...rest } = pc
    void _p
    out.push({ ...rest, prerequisiteRecords: created, ready: !pc.needsRules || rulesSupplied, readinessNote: !pc.needsRules ? 'Ready to export' : rulesSupplied ? 'Ready: expected behaviour taken from supplied rules / API contract' : 'Needs application rules or an API contract: the schema alone cannot define this behaviour' })
  }
  for (const tc of out) {
    if (!tc.fixture) continue
    for (const f of target.foreignKeys) {
      if (f.column in tc.fixture.body! && tc.fixture.body![f.column] === null) {
        const first = ctx.dataset[f.refTable]?.[0]
        if (first) tc.fixture.body![f.column] = first[f.refColumn]
      }
    }
  }
  c.job.testCases = out
  c.dataset = ctx.dataset
  for (const [k, v] of Object.entries(c.dataset)) c.requested[k] = v.length
}

async function run(c: JobCtx) {
  const { job } = c
  const set = (i: number, state: 'running' | 'done' | 'failed', detail?: string) => {
    job.stages[i] = { ...job.stages[i], state, detail }
  }
  try {
    for (let i = 0; i < job.stages.length; i++) {
      set(i, 'running')
      await sleep(350 + Math.random() * 350)
      const id = job.stages[i].id
      let detail: string | undefined
      if (id === 'bp' || (id === 'ai' && job.config.mode === 'scenario')) {
        if (id === 'ai') job.blueprint = planBlueprint(c.schema, job.config)
        else detail = `${job.blueprint!.scenarios.length} scenario(s), ${job.blueprint!.tableCounts.length} table count(s) accepted`
      }
      if (id === 'rows') {
        const counts = job.config.mode === 'scenario' ? job.blueprint!.tableCounts : job.config.tables
        generateTables(c, counts, job.blueprint)
        detail = `${Object.values(c.dataset).reduce((s, r) => s + r.length, 0)} records created`
      }
      if (id === 'ai' && job.config.mode === 'testcase') detail = 'Structured JSON plan received'
      if (id === 'prereq') {
        generateTestCases(c)
        detail = `${job.testCases!.length} cases, ${Object.values(c.dataset).reduce((s, r) => s + r.length, 0)} prerequisite records`
      }
      if (id === 'scenarios') {
        c.coverage = scenarioCoverage(c.dataset, c.schema, job.blueprint?.scenarios ?? [])
        detail = `${c.coverage.filter((x) => x.result === 'Covered').length}/${c.coverage.length} covered`
      }
      if (id === 'validate') {
        c.unsupported = [...new Set([...c.unsupported, ...unsupportedConstraints(c.schema)])]
        job.report = buildReport(c)
        detail = `${job.report.checks.filter((k) => k.status === 'passed').length} passed`
      }
      set(i, 'done', detail)
    }
    job.status = job.report!.status
  } catch (e) {
    const i = job.stages.findIndex((s) => s.state === 'running')
    if (i >= 0) set(i, 'failed', (e as Error).message)
    job.error = (e as Error).message
    job.status = 'failed'
  }
}

const snapshot = (j: Job): Job => JSON.parse(JSON.stringify(j))
const need = (id: string) => {
  const c = jobs.get(id)
  if (!c) throw new Error('Job not found. Generated datasets live in server memory and may have expired. Please generate again.')
  return c
}

export const mockApi: Api = {
  mode: 'mock',

  async listTargets() {
    await sleep(150)
    return APPROVED_TARGETS
  },

  async testConnection(req) {
    await sleep(900)
    const target = matchTarget(req)
    const dbType = req.dbType
    if (!target)
      return { ok: false, dbType, database: req.database ?? '', metadataAccess: 'Denied', tablesDiscovered: 0, message: 'Destination is not on the approved network policy. Use a registered test connection.' }
    if (target.dbType !== dbType)
      return { ok: false, dbType, database: target.database, metadataAccess: 'Denied', tablesDiscovered: 0, message: 'The registered target is a different database type.' }
    if (dbType !== 'mongodb' && !req.password?.trim() && !req.targetId)
      return { ok: false, dbType, database: target.database, metadataAccess: 'Denied', tablesDiscovered: 0, message: 'Authentication failed for the supplied user. Check the username and password.' }
    const schema = buildSchema(target.id)
    return { ok: true, dbType, database: target.database, metadataAccess: 'Allowed', tablesDiscovered: schema.tables.length, targetId: target.id, message: 'Connection successful. Metadata-only access confirmed.' }
  },

  async fetchSchema(targetId) {
    await sleep(1800)
    return buildSchema(targetId)
  },

  async parseCollection() {
    throw new Error('Reading a Postman collection needs the backend. Set VITE_API_BASE to the FastAPI origin.')
  },
  async planBlueprint(schema, config) {
    await sleep(500)
    return planBlueprint(schema, config)
  },

  async createJob(schema, config) {
    const id = `job_${(++seq).toString().padStart(4, '0')}${Math.random().toString(36).slice(2, 6)}`
    const job: Job = { id, config, status: 'running', stages: STAGES[config.mode].map((s) => ({ ...s, state: 'pending' as const })) }
    const c: JobCtx = { job, schema, dataset: {}, order: [], links: {}, adjustments: [], unsupported: [], requested: {}, started: performance.now(), hasSpec: false }
    jobs.set(id, c)
    void run(c)
    return { jobId: id }
  },

  async getJob(id) {
    return snapshot(need(id).job)
  },

  async getPreview(id, table, page, pageSize) {
    const c = need(id)
    const rows = c.dataset[table] ?? []
    const t = c.schema.tables.find((x) => x.name === table)
    const slice = rows.slice(page * pageSize, (page + 1) * pageSize)
    const links: Record<number, string[]> = {}
    if (c.links[table]) slice.forEach((r, i) => { const l = c.links[table][c.ctx!.pkOf(table, r)]; if (l) links[i] = l })
    return { table, total: rows.length, page, pageSize, columns: t?.columns.map((x) => x.name) ?? Object.keys(rows[0] ?? {}), rows: slice, links: Object.keys(links).length ? links : undefined }
  },

  async generateMissing(id) {
    await sleep(700)
    const c = need(id)
    const ctx = c.ctx!
    for (const cov of c.coverage ?? []) {
      if (cov.result !== 'Missing' && cov.result !== 'Partial') continue
      const s = cov.scenario
      const t = c.schema.tables.find((x) => x.name === s.table)!
      if (t.foreignKeys.some((f) => f.refTable !== t.name && !(c.dataset[f.refTable]?.length))) continue
      for (let i = 0; i < s.count - cov.generated; i++) ctx.addRow(s.table, { [s.column]: s.value })
      c.requested[s.table] = Math.max(c.requested[s.table] ?? 0, c.dataset[s.table].length)
    }
    c.coverage = scenarioCoverage(c.dataset, c.schema, c.job.blueprint?.scenarios ?? [])
    c.adjustments = c.adjustments.filter((a) => !a.startsWith('Scenario'))
    c.job.report = buildReport(c)
    c.job.status = c.job.report.status
    return snapshot(c.job)
  },

  async exportFile(id, format) {
    await sleep(300)
    const c = need(id)
    if (!c.job.report) throw new Error('Job has no report yet.')
    return buildExport(format, { schema: c.schema, dataset: c.dataset, order: c.order, report: c.job.report, testCases: c.job.testCases, apiBaseUrl: c.apiBaseUrl, hasSpec: c.hasSpec })
  },

  async getLoadPlan(id, targetId) {
    const c = need(id)
    const target = APPROVED_TARGETS.find((t) => t.id === targetId)
    if (!target) throw new Error('Target is not on the approved list.')
    return { target, tables: c.order.filter((t) => c.dataset[t]?.length).map((t) => ({ table: t, expected: c.dataset[t].length })) }
  },

  async startLoad(id, targetId) {
    const c = need(id)
    const target = APPROVED_TARGETS.find((t) => t.id === targetId)
    if (!target) throw new Error('Target is not on the approved list.')
    if (!target.loadAllowed) throw new Error('Direct load is only enabled for the PostgreSQL test schema in the MVP.')
    const loadId = `load_${Math.random().toString(36).slice(2, 8)}`
    const plan = c.order.filter((t) => c.dataset[t]?.length).map((t) => ({ table: t, expected: c.dataset[t].length }))
    loads.set(loadId, {
      id: loadId,
      ctxId: id,
      t0: Date.now(),
      plan,
      status: 'running',
      boomiStatus: 'RECEIVED',
      verification: { countsMatch: false, fkValid: false },
      perTable: plan.map((p) => ({ ...p, inserted: 0, failedBatches: 0 })),
      steps: [
        { id: 'confirm', layer: 'React', label: 'Load approved by user', state: 'done' },
        { id: 'job', layer: 'FastAPI', label: 'Create load job, check target against approved list', state: 'pending' },
        { id: 'recv', layer: 'Boomi', label: 'Web Services Server receives approved request', state: 'pending' },
        { id: 'batch', layer: 'Boomi', label: 'Retrieve batch reference for the job', state: 'pending' },
        { id: 'adapter', layer: 'Boomi', label: 'Choose load adapter (MVP: Python database adapter)', state: 'pending' },
        { id: 'insert', layer: 'Database', label: 'Insert parents first, in batches', state: 'pending' },
        { id: 'status', layer: 'Boomi', label: 'Try/Catch then return batch status', state: 'pending' },
        { id: 'verify', layer: 'FastAPI', label: 'Verify counts and foreign keys', state: 'pending' },
      ],
    })
    return { loadId }
  },

  async getLoad(loadId) {
    const l = loads.get(loadId)
    if (!l) throw new Error('Load job not found.')
    const elapsed = Date.now() - l.t0
    const total = l.plan.length
    const stepAt = [0, 600, 1200, 1800, 2400] // job, recv, batch, adapter, insert start
    const insertMs = 900 * total
    const phase = (ms: number) => elapsed >= ms
    const states: Record<string, 'pending' | 'running' | 'done'> = {}
    const order = ['job', 'recv', 'batch', 'adapter']
    order.forEach((id, i) => (states[id] = phase(stepAt[i + 1]) ? 'done' : phase(stepAt[i]) ? 'running' : 'pending'))
    const insStart = stepAt[4]
    states.insert = phase(insStart + insertMs) ? 'done' : phase(insStart) ? 'running' : 'pending'
    states.status = phase(insStart + insertMs + 600) ? 'done' : phase(insStart + insertMs) ? 'running' : 'pending'
    states.verify = phase(insStart + insertMs + 1500) ? 'done' : phase(insStart + insertMs + 600) ? 'running' : 'pending'
    const steps = l.steps.map((s) => (states[s.id] ? { ...s, state: states[s.id] } : s))
    const perTable = l.plan.map((p, i) => {
      const prog = Math.min(1, Math.max(0, (elapsed - insStart - i * 900) / 900))
      return { ...p, inserted: Math.round(p.expected * prog), failedBatches: 0 }
    })
    const done = states.verify === 'done'
    const c = jobs.get(l.ctxId)
    const verification = done && c ? { countsMatch: perTable.every((p) => p.inserted === (c.dataset[p.table]?.length ?? -1)), fkValid: c.job.report?.checks.find((k) => k.id === 'fk')?.failed === 0 } : { countsMatch: false, fkValid: false }
    const ok = done && verification.countsMatch && verification.fkValid
    return {
      id: l.id,
      steps,
      perTable,
      verification,
      boomiStatus: done ? (ok ? 'COMPLETE' : 'ERROR') : states.status === 'done' ? 'COMPLETE (verifying)' : 'EXECUTING',
      status: done ? (ok ? 'success' : 'failed') : 'running',
    }
  },
}
