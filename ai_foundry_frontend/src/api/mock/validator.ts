// src/api/mock/validator.ts
import type { Column, Row, Scenario, ScenarioCoverage, Schema, TestCase, ValidationCheck } from '../../types'
import { isDate, isInt, isNum, isText, parseRange, type Dataset } from './engine'

export function scenarioCoverage(dataset: Dataset, schema: Schema, scenarios: Scenario[]): ScenarioCoverage[] {
  return scenarios.map((s) => {
    const table = schema.tables.find((t) => t.name === s.table)
    const col = table?.columns.find((c) => c.name === s.column)
    if (!table || !col) {
      return { scenario: s, generated: 0, result: 'Unsupported', note: `Schema has no ${s.table}.${s.column}. The requested state cannot be represented.` }
    }
    if (col.enumValues && !col.enumValues.includes(s.value)) {
      return { scenario: s, generated: 0, result: 'Unsupported', note: `${s.value} is not permitted by the ${s.column} constraint (${col.enumValues.join(', ')}).` }
    }
    const generated = (dataset[s.table] ?? []).filter((r) => String(r[s.column]).toUpperCase() === s.value.toUpperCase()).length
    const result = generated >= s.count ? 'Covered' : generated === 0 ? 'Missing' : 'Partial'
    return { scenario: s, generated, result, note: result === 'Covered' ? undefined : `${s.count - generated} more required.` }
  })
}

function typeOk(c: Column, v: Row[string]): boolean {
  const t = c.type.toLowerCase()
  if (t === 'objectid') return typeof v === 'string' && /^[0-9a-f]{24}$/.test(v)
  if (t === 'uuid') return typeof v === 'string' && /^[0-9a-f-]{36}$/.test(v)
  if (t === 'boolean' || t === 'bool') return typeof v === 'boolean'
  if (isInt(t)) return typeof v === 'number' && Number.isInteger(v)
  if (isNum(t)) return typeof v === 'number' && Number.isFinite(v)
  if (isDate(t)) return typeof v === 'string' && !Number.isNaN(Date.parse(v))
  if (isText(t)) return typeof v === 'string'
  return true
}

export function validate(opts: {
  schema: Schema
  dataset: Dataset
  coverage?: ScenarioCoverage[]
  testCases?: TestCase[]
}): ValidationCheck[] {
  const { schema, dataset, coverage, testCases } = opts
  const tables = schema.tables.filter((t) => dataset[t.name])
  const acc = { type: [0, 0], req: [0, 0], len: [0, 0], pk: [0, 0], fk: [0, 0], uq: [0, 0], en: [0, 0] }
  const bump = (k: keyof typeof acc, ok: boolean) => {
    acc[k][0]++
    if (!ok) acc[k][1]++
  }
  for (const t of tables) {
    const rows = dataset[t.name]
    const pkSets = new Map<string, Set<string>>()
    const uqSets = new Map<string, Set<string>>()
    for (const c of t.columns) {
      if (c.primaryKey) pkSets.set(c.name, new Set())
      else if (c.unique) uqSets.set(c.name, new Set())
    }
    for (const r of rows) {
      for (const c of t.columns) {
        const v = r[c.name]
        if (v === null || v === undefined) {
          bump('req', c.nullable || c.missing === true)
          continue
        }
        bump('req', true)
        bump('type', typeOk(c, v))
        if (c.maxLength && typeof v === 'string') bump('len', v.length <= c.maxLength)
        if (c.enumValues) bump('en', c.enumValues.includes(String(v)))
        if (c.check && typeof v === 'number') {
          const { min, max } = parseRange(c.check)
          bump('en', (min === undefined || v >= min) && (max === undefined || v <= max))
        }
        const pks = pkSets.get(c.name)
        if (pks) {
          bump('pk', !pks.has(String(v)))
          pks.add(String(v))
        }
        const uqs = uqSets.get(c.name)
        if (uqs) {
          bump('uq', !uqs.has(String(v)))
          uqs.add(String(v))
        }
      }
      for (const f of t.foreignKeys) {
        const v = r[f.column]
        if (v === null || v === undefined) continue
        const parent = f.refTable === t.name ? rows : dataset[f.refTable]
        bump('fk', !!parent?.some((p) => p[f.refColumn] === v))
      }
    }
  }
  const mk = (id: string, label: string, [checked, failed]: number[], detail?: string): ValidationCheck => ({
    id,
    label,
    checked,
    failed,
    status: failed > 0 ? 'failed' : 'passed',
    detail: detail ?? (failed ? `${failed} of ${checked} checked values failed` : `${checked} values checked`),
  })
  const checks: ValidationCheck[] = [
    mk('type', 'Data type matches field', acc.type),
    mk('required', 'Required fields not null', acc.req),
    mk('length', 'String length within limit', acc.len),
    mk('pk', 'Primary key unique', acc.pk),
    mk('fk', 'Foreign key references a parent', acc.fk),
    mk('unique', 'Unique constraint holds', acc.uq),
    mk('enum', 'Enum and check constraints', acc.en),
  ]
  if (coverage?.length) {
    const bad = coverage.filter((c) => c.result !== 'Covered')
    checks.push({
      id: 'scenario',
      label: 'Scenario counts match request',
      checked: coverage.length,
      failed: bad.length,
      status: bad.length ? 'warning' : 'passed',
      detail: bad.length ? `${bad.length} scenario(s) not fully covered` : `${coverage.length} scenario(s) covered`,
    })
  } else {
    checks.push({ id: 'scenario', label: 'Scenario counts match request', checked: 0, failed: 0, status: 'skipped', detail: 'No scenarios requested' })
  }
  if (testCases) {
    const need = testCases.filter((tc) => tc.prerequisiteRecords.length)
    const bad = need.filter((tc) => tc.prerequisiteRecords.some((p) => !dataset[p.table]?.some((r) => Object.values(r).some((x) => String(x) === p.key))))
    checks.push({
      id: 'linkage',
      label: 'Test-case linkage exists',
      checked: need.length,
      failed: bad.length,
      status: bad.length ? 'failed' : 'passed',
      detail: `${need.length - bad.length} of ${need.length} cases have all prerequisite records`,
    })
  } else {
    checks.push({ id: 'linkage', label: 'Test-case linkage exists', checked: 0, failed: 0, status: 'skipped', detail: 'Mode 3 only' })
  }
  return checks
}

export function unsupportedConstraints(schema: Schema): string[] {
  const out: string[] = []
  for (const t of schema.tables) {
    for (const c of t.columns) {
      if (c.check) {
        const r = parseRange(c.check)
        if (r.min === undefined && r.max === undefined) out.push(`${t.name}.${c.name}: check "${c.check}" is not automatically validated`)
      }
    }
    if (t.needsDefinition) out.push(`${t.name}: no validator, fields were not discovered`)
  }
  if (schema.dbType === 'mongodb') out.push('Cross-collection references are not discoverable from MongoDB metadata')
  return out
}
