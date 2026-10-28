// src/api/mock/ai.ts
import type { Blueprint, JobConfig, Scenario, Schema, Table, TableCount, TestCase, TestCategory } from '../../types'
import { isDate, isInt, isNum, isText, parseRange, type GenContext } from './engine'

const singular = (w: string) => (w.endsWith('ies') ? w.slice(0, -3) + 'y' : w.endsWith('s') ? w.slice(0, -1) : w)
const words = (s: string) => s.toLowerCase().replace(/_/g, ' ')

/** All phrases a table can be called in prose: "placement providers", "provider", ... */
function aliases(t: Table): string[] {
  const parts = words(t.name).split(' ')
  const out = new Set<string>()
  for (let i = 0; i < parts.length; i++) {
    const tail = parts.slice(i)
    out.add(tail.join(' '))
    out.add([...tail.slice(0, -1), singular(tail.at(-1)!)].join(' '))
  }
  return [...out].sort((a, b) => b.length - a.length)
}

export function findTable(schema: Schema, text: string): { table: Table; rest: string } | undefined {
  const t = words(text).trim()
  for (const table of schema.tables) {
    for (const a of aliases(table)) {
      if (t.endsWith(a)) return { table, rest: t.slice(0, t.length - a.length).trim() }
    }
  }
  return undefined
}

/** Stand-in for the hosted LLM: turns free text into a structured blueprint. The real service returns the same shape. */
export function planBlueprint(schema: Schema, config: JobConfig): Blueprint {
  const text = config.description ?? ''
  const notes: string[] = []
  const counts = new Map<string, number>(config.tables.map((t) => [t.table, t.count]))
  const scenarios: Scenario[] = [...(config.scenarios ?? [])]
  const clauses = text.split(/[,;\n]|\band\b|\.(?=\s|$)/i).map((c) => c.trim()).filter(Boolean)

  for (const clause of clauses) {
    const m = clause.match(/(?:generate|create|add|include|with)?\s*(\d[\d,]*)\s+(.+)$/i)
    if (!m) continue
    const n = Number(m[1].replace(/,/g, ''))
    const hit = findTable(schema, m[2])
    if (!hit) continue
    if (!hit.rest) {
      counts.set(hit.table.name, n)
      continue
    }
    const state = hit.rest.split(' ').at(-1)!.toUpperCase()
    const enumCol = hit.table.columns.find((c) => c.enumValues?.some((v) => v.toUpperCase() === state)) ?? hit.table.columns.find((c) => c.name === 'status')
    scenarios.push({ table: hit.table.name, column: enumCol?.name ?? 'status', value: state, count: n })
  }

  const domain = text.trim() || 'Generic application (no description supplied)'
  const localeHint = /india/i.test(text) ? 'en_IN' : /\b(uk|british|england)\b/i.test(text) ? 'en_GB' : config.locale
  const columnRules: Blueprint['columnRules'] = []
  for (const t of schema.tables) {
    for (const c of t.columns) {
      if (c.enumValues && !c.primaryKey) columnRules.push({ table: t.name, column: c.name, rule: `Weighted choice over ${c.enumValues.join(' / ')}` })
    }
  }
  const emailCols = schema.tables.flatMap((t) => t.columns.filter((c) => c.name.includes('email')).map((c) => `${t.name}.${c.name}`))
  if (emailCols.length) notes.push(`Locale-appropriate unique e-mail addresses for ${emailCols.slice(0, 3).join(', ')}${emailCols.length > 3 ? '…' : ''}`)
  const perTable = new Map<string, number>()
  for (const s of scenarios) perTable.set(s.table, (perTable.get(s.table) ?? 0) + s.count)
  for (const [table, total] of perTable) {
    const have = counts.get(table) ?? 0
    if (have && total > have) notes.push(`Scenario total for ${table} (${total}) exceeds the requested record count (${have}); some scenarios will be reported as missing.`)
  }
  if (!text.trim()) notes.push('No application description given, so only scenarios and counts were applied.')
  return {
    domain,
    localeHint,
    tableCounts: [...counts].map(([table, count]) => ({ table, count })) as TableCount[],
    scenarios,
    columnRules: columnRules.slice(0, 8),
    notes,
  }
}

/* ------------------------------ Mode 3 ------------------------------ */

export interface PlannedCase extends Omit<TestCase, 'prerequisiteRecords' | 'ready' | 'readinessNote'> {
  prereq: { kind: 'parents' } | { kind: 'row'; forced: Record<string, string | number | boolean | null> } | { kind: 'none' }
}

function pickTarget(schema: Schema, feature: string): Table {
  const f = words(feature)
  let best: { t: Table; score: number } | undefined
  for (const t of schema.tables) {
    const hit = aliases(t).find((a) => f.includes(a))
    const score = (hit ? 100 + hit.length : 0) + t.foreignKeys.length + (t.columns.some((c) => c.enumValues && c.name === 'status') ? 2 : 0)
    if (!best || score > best.score) best = { t, score }
  }
  return best!.t
}

export function planTestCases(
  schema: Schema,
  feature: string,
  categories: TestCategory[],
  ctx: GenContext,
  endpoint?: { method: string; path: string },
): { cases: PlannedCase[]; target: Table } {
  const target = pickTarget(schema, feature)
  const sing = singular(words(target.name))
  const path = endpoint?.path ?? `/api/v1/${target.name.replace(/_/g, '-')}`
  const base = (forced: Record<string, string | number | boolean | null> = {}) => {
    const row = ctx.sampleRow(target.name, forced)
    const body: Record<string, unknown> = {}
    for (const c of target.columns) if (!(c.primaryKey && isInt(c.type)) && row[c.name] !== undefined) body[c.name] = row[c.name]
    return body
  }
  const cases: PlannedCase[] = []
  let n = 0
  const add = (c: Omit<PlannedCase, 'id' | 'table'>) => cases.push({ ...c, id: `TC${String(++n).padStart(3, '0')}`, table: target.name })
  const post = { method: 'POST', path }
  const statusCol = target.columns.find((c) => c.enumValues && /status|state/.test(c.name))
  const requiredFks = target.foreignKeys.filter((f) => !target.columns.find((c) => c.name === f.column)?.nullable)
  const fkCols = new Set(target.foreignKeys.map((f) => f.column))
  const numeric = target.columns.filter((c) => !c.primaryKey && !fkCols.has(c.name) && (isNum(c.type) || isInt(c.type)) && !/year/.test(c.name))

  if (categories.includes('positive')) {
    add({ category: 'positive', title: `Create ${sing} with valid data`, preconditions: ['All parent records exist'], steps: [`POST ${path} with a complete valid body`], expected: 'Submission accepted (HTTP 201) and the record is stored', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base() } })
    const optional = target.columns.filter((c) => c.nullable)
    if (optional.length) add({ category: 'positive', title: `Create ${sing} without optional fields (${optional.map((c) => c.name).join(', ')})`, preconditions: ['All parent records exist'], steps: [`POST ${path} omitting optional fields`], expected: 'Submission accepted (HTTP 201)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: Object.fromEntries(Object.entries(base()).filter(([k]) => !optional.some((o) => o.name === k))) } })
    for (const v of (statusCol?.enumValues ?? []).slice(0, 2)) add({ category: 'positive', title: `Create ${sing} with ${statusCol!.name} = ${v}`, preconditions: ['All parent records exist'], steps: [`POST ${path} with ${statusCol!.name}=${v}`], expected: 'Submission accepted (HTTP 201)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base({ [statusCol!.name]: v }) } })
  }

  if (categories.includes('negative')) {
    for (const f of requiredFks.slice(0, 3)) {
      const body = base()
      delete body[f.column]
      add({ category: 'negative', title: `Create ${sing} without ${f.column}`, preconditions: ['Parent records exist'], steps: [`POST ${path} omitting ${f.column}`], expected: 'Validation error (HTTP 422)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body } })
    }
    const first = requiredFks[0]
    if (first) add({ category: 'negative', title: `Create ${sing} referencing a non-existent ${first.refTable} record`, preconditions: [], steps: [`POST ${path} with ${first.column}=DOES_NOT_EXIST`], expected: 'Rejected, foreign key violation (HTTP 409/422)', needsRules: false, prereq: { kind: 'none' }, fixture: { ...post, body: base({ [first.column]: 'DOES_NOT_EXIST' }) } })
    for (const c of numeric.slice(0, 2)) add({ category: 'negative', title: `Create ${sing} with negative ${c.name.replace(/_/g, ' ')}`, preconditions: ['Parent records exist'], steps: [`POST ${path} with ${c.name}=-1`], expected: 'Validation error (HTTP 422)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base({ [c.name]: -1 }) } })
    const wrongType = target.columns.find((c) => isText(c.type) && !c.enumValues && !c.primaryKey && !target.foreignKeys.some((f) => f.column === c.name))
    if (wrongType) add({ category: 'negative', title: `Create ${sing} with wrong data type for ${wrongType.name}`, preconditions: [], steps: [`POST ${path} with ${wrongType.name}=12345 (number)`], expected: 'Validation error (HTTP 422)', needsRules: false, prereq: { kind: 'none' }, fixture: { ...post, body: base({ [wrongType.name]: 12345 }) } })
    add({ category: 'negative', title: `Submit duplicate ${sing}`, preconditions: [`An identical ${sing} already exists`], steps: [`POST ${path} twice with the same body`], expected: 'Duplicate-handling rule enforced (needs supplied rule)', needsRules: true, prereq: { kind: 'row', forced: {} }, fixture: { ...post, body: base() } })
    if (target.name === 'timesheets' || statusCol) add({ category: 'negative', title: `Student attempts unauthorized approval of ${sing}`, preconditions: [`A ${sing} awaiting review exists`, 'Caller is not the placement supervisor'], steps: ['Authenticate as student', `PATCH ${path}/{id} with approved status`], expected: 'Access denied (needs supplied permission rule)', needsRules: true, prereq: { kind: 'row', forced: statusCol ? { [statusCol.name]: statusCol.enumValues![0] } : {} } })
  }

  if (categories.includes('boundary')) {
    for (const c of numeric.slice(0, 2)) {
      const { min, max } = parseRange(c.check)
      const lo = min ?? 0
      const hi = max ?? lo + 100
      add({ category: 'boundary', title: `${c.name.replace(/_/g, ' ')} at minimum (${lo})`, preconditions: ['Parent records exist'], steps: [`POST ${path} with ${c.name}=${lo}`], expected: 'Accepted (HTTP 201)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base({ [c.name]: lo }) } })
      add({ category: 'boundary', title: `${c.name.replace(/_/g, ' ')} at maximum (${hi})`, preconditions: ['Parent records exist'], steps: [`POST ${path} with ${c.name}=${hi}`], expected: 'Accepted (HTTP 201)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base({ [c.name]: hi }) } })
      if (max !== undefined) add({ category: 'boundary', title: `${c.name.replace(/_/g, ' ')} just above maximum (${hi + 1})`, preconditions: [], steps: [`POST ${path} with ${c.name}=${hi + 1}`], expected: 'Validation error (HTTP 422)', needsRules: false, prereq: { kind: 'none' }, fixture: { ...post, body: base({ [c.name]: hi + 1 }) } })
    }
    const lenCol = target.columns.find((c) => c.maxLength && isText(c.type) && !c.enumValues && !c.primaryKey && !fkCols.has(c.name))
    if (lenCol) add({ category: 'boundary', title: `${lenCol.name} one character over limit (${lenCol.maxLength! + 1})`, preconditions: [], steps: [`POST ${path} with ${lenCol.name} of ${lenCol.maxLength! + 1} chars`], expected: 'Validation error (HTTP 422)', needsRules: false, prereq: { kind: 'none' }, fixture: { ...post, body: base({ [lenCol.name]: 'x'.repeat(lenCol.maxLength! + 1) }) } })
    const d = target.columns.find((c) => isDate(c.type))
    if (d) add({ category: 'boundary', title: `${d.name} set to today`, preconditions: ['Parent records exist'], steps: [`POST ${path} with ${d.name}=today`], expected: 'Accepted (HTTP 201)', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base({ [d.name]: new Date().toISOString().slice(0, d.type === 'date' ? 10 : 24) }) } })
  }

  if (categories.includes('workflow')) {
    const states = statusCol?.enumValues ?? []
    const initial = states.find((s) => /SUBMITTED|PENDING|PLACED|OPEN/.test(s)) ?? states[0]
    const decided = states.filter((s) => s !== initial && !/PENDING|SUBMITTED|PLACED|OPEN/.test(s))
    const next = decided.length ? decided : states.filter((s) => s !== initial)
    if (statusCol && initial) {
      for (const s of next.slice(0, 4)) {
        const verb = /APPROVED/.test(s) ? 'Supervisor approves' : /REJECTED/.test(s) ? 'Supervisor rejects' : /QUERIED/.test(s) ? 'Supervisor queries' : `Move ${sing} to ${s} for`
        add({ category: 'workflow', title: `${verb} ${initial.toLowerCase()} ${sing}`, preconditions: [`${sing} exists with ${statusCol.name}=${initial}`, 'Authorized reviewer exists'], steps: [`Authenticate as authorized reviewer`, `PATCH ${path}/{id} setting ${statusCol.name}=${s}`], expected: `Status becomes ${s}`, needsRules: false, prereq: { kind: 'row', forced: { [statusCol.name]: initial } }, fixture: { method: 'PATCH', path: `${path}/{id}`, body: { [statusCol.name]: s } } })
      }
    }
    add({ category: 'workflow', title: `End-to-end: create ${sing} then retrieve it`, preconditions: ['Parent records exist'], steps: [`POST ${path}`, `GET ${path}/{id}`], expected: 'Retrieved record matches the submitted body', needsRules: false, prereq: { kind: 'parents' }, fixture: { ...post, body: base() } })
  }
  return { cases, target }
}
