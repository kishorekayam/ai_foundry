import * as XLSX from 'xlsx'
import JSZip from 'jszip'
import type { ExportFormat, Report, Row, Schema, TestCase } from '../../types'
import type { Dataset } from './engine'

export interface ExportInput {
  schema: Schema
  dataset: Dataset
  order: string[]
  report: Report
  testCases?: TestCase[]
  apiBaseUrl?: string
  hasSpec: boolean
}

export interface ExportFile {
  blob: Blob
  filename: string
}

const stamp = 'atom_foundry'
const tableNames = (i: ExportInput) => i.order.filter((t) => i.dataset[t])

const wbBlob = (wb: XLSX.WorkBook) =>
  new Blob([XLSX.write(wb, { type: 'array', bookType: 'xlsx' })], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })

const csvCell = (v: unknown) => {
  if (v === null || v === undefined) return ''
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
const toCsv = (rows: Row[], cols: string[]) => [cols.join(','), ...rows.map((r) => cols.map((c) => csvCell(r[c])).join(','))].join('\n')

const sqlLit = (v: Row[string]) => (v === null || v === undefined ? 'NULL' : typeof v === 'number' ? String(v) : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : `'${String(v).replace(/'/g, "''")}'`)

function sqlScript(i: ExportInput, q: (s: string) => string, dialect: string) {
  const lines = [`-- ATOM DATA FOUNDRY synthetic data (${dialect})`, `-- Database: ${i.schema.database}`, `-- Generated: ${new Date().toISOString()}`, 'BEGIN;', '']
  for (const t of tableNames(i)) {
    const rows = i.dataset[t]
    if (!rows.length) continue
    const cols = Object.keys(rows[0])
    lines.push(`-- ${t}: ${rows.length} rows`)
    for (let k = 0; k < rows.length; k += 100) {
      const chunk = rows.slice(k, k + 100)
      lines.push(`INSERT INTO ${q(t)} (${cols.map(q).join(', ')}) VALUES`, chunk.map((r) => `  (${cols.map((c) => sqlLit(r[c])).join(', ')})`).join(',\n') + ';')
    }
    lines.push('')
  }
  lines.push('COMMIT;')
  return lines.join('\n')
}

function caseRows(i: ExportInput) {
  return (i.testCases ?? []).map((t) => ({
    'Test ID': t.id,
    Category: t.category,
    Title: t.title,
    Table: t.table,
    Preconditions: t.preconditions.join('\n'),
    Steps: t.steps.map((s, k) => `${k + 1}. ${s}`).join('\n'),
    'Expected result': t.expected,
    'Needs rules / API contract': t.needsRules ? 'Yes' : 'No',
    Ready: t.ready ? 'Ready' : 'Needs input',
    'Prerequisite records': t.prerequisiteRecords.map((p) => `${p.table}:${p.key}`).join(', '),
  }))
}

const mappingRows = (i: ExportInput) =>
  (i.testCases ?? []).flatMap((t) =>
    t.prerequisiteRecords.length
      ? t.prerequisiteRecords.map((p) => ({ 'Test ID': t.id, Title: t.title, Table: p.table, 'Record key': p.key }))
      : [{ 'Test ID': t.id, Title: t.title, Table: '(none, API fixture only)', 'Record key': '' }],
  )

function postman(i: ExportInput) {
  const base = i.apiBaseUrl || '{{baseUrl}}'
  return {
    info: { name: `ATOM DATA FOUNDRY - ${i.schema.database}`, schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json' },
    variable: [{ key: 'baseUrl', value: i.apiBaseUrl || 'http://localhost:8000' }],
    item: (i.testCases ?? [])
      .filter((t) => t.fixture)
      .map((t) => ({
        name: `${t.id} ${t.title}`,
        request: {
          method: t.fixture!.method,
          header: [{ key: 'Content-Type', value: 'application/json' }],
          url: { raw: `${base}${t.fixture!.path}`, host: [base], path: t.fixture!.path.split('/').filter(Boolean) },
          body: { mode: 'raw', raw: JSON.stringify(t.fixture!.body, null, 2) },
        },
        event: [
          {
            listen: 'test',
            script: {
              type: 'text/javascript',
              exec: [
                /\b4\d\d\b|error|denied/i.test(t.expected)
                  ? 'pm.test("Request is rejected", () => pm.expect(pm.response.code).to.be.within(400, 499));'
                  : 'pm.test("Request succeeds", () => pm.expect(pm.response.code).to.be.within(200, 299));',
              ],
            },
          },
        ],
      })),
  }
}

function pytest(i: ExportInput) {
  const out = ['import os', 'import httpx', '', 'BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")', '']
  for (const t of i.testCases ?? []) {
    if (!t.fixture) continue
    const neg = /\b4\d\d\b|error|denied/i.test(t.expected)
    out.push(
      `def test_${t.id.toLowerCase()}_${t.title.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 48)}():`,
      `    """${t.title}. Expected: ${t.expected}"""`,
      `    r = httpx.request("${t.fixture.method}", f"{BASE_URL}${t.fixture.path}", json=${JSON.stringify(t.fixture.body)})`,
      neg ? '    assert 400 <= r.status_code < 500' : '    assert 200 <= r.status_code < 300',
      '',
    )
  }
  return out.join('\n')
}

export async function buildExport(format: ExportFormat, i: ExportInput): Promise<ExportFile> {
  const names = tableNames(i)
  switch (format) {
    case 'xlsx': {
      const wb = XLSX.utils.book_new()
      for (const t of names) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(i.dataset[t]), t.slice(0, 31))
      return { blob: wbBlob(wb), filename: `${stamp}_data.xlsx` }
    }
    case 'csv-zip': {
      const zip = new JSZip()
      for (const t of names) zip.file(`${t}.csv`, toCsv(i.dataset[t], i.schema.tables.find((x) => x.name === t)!.columns.map((c) => c.name)))
      zip.file('schema_manifest.json', JSON.stringify({ database: i.schema.database, dbType: i.schema.dbType, tables: i.schema.tables.filter((t) => i.dataset[t.name]), loadOrder: names }, null, 2))
      zip.file('validation_report.json', JSON.stringify(i.report, null, 2))
      if (i.testCases) zip.file('test_case_data_mapping.csv', toCsv(mappingRows(i) as unknown as Row[], ['Test ID', 'Title', 'Table', 'Record key']))
      return { blob: await zip.generateAsync({ type: 'blob' }), filename: `${stamp}_data.zip` }
    }
    case 'json':
      return { blob: new Blob([JSON.stringify(Object.fromEntries(names.map((t) => [t, i.dataset[t]])), null, 2)], { type: 'application/json' }), filename: `${stamp}_data.json` }
    case 'sql-postgres':
      return { blob: new Blob([sqlScript(i, (s) => `"${s}"`, 'PostgreSQL')], { type: 'text/plain' }), filename: `${stamp}_postgres.sql` }
    case 'sql-mysql':
      return { blob: new Blob([sqlScript(i, (s) => `\`${s}\``, 'MySQL').replace('BEGIN;', 'START TRANSACTION;')], { type: 'text/plain' }), filename: `${stamp}_mysql.sql` }
    case 'testcase-xlsx': {
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(caseRows(i)), 'Test cases')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(mappingRows(i)), 'Data mapping')
      return { blob: wbBlob(wb), filename: `${stamp}_test_cases.xlsx` }
    }
    case 'postman':
      return { blob: new Blob([JSON.stringify(postman(i), null, 2)], { type: 'application/json' }), filename: `${stamp}_postman_collection.json` }
    case 'pytest':
      return { blob: new Blob([pytest(i)], { type: 'text/x-python' }), filename: `test_${stamp}.py` }
    case 'mapping-report': {
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(mappingRows(i)), 'Mapping')
      return { blob: wbBlob(wb), filename: `${stamp}_test_data_mapping.xlsx` }
    }
    case 'report-json':
      return { blob: new Blob([JSON.stringify(i.report, null, 2)], { type: 'application/json' }), filename: `${stamp}_report.json` }
    case 'report-xlsx': {
      const r = i.report
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(
        wb,
        XLSX.utils.json_to_sheet([
          { Metric: 'Database type', Value: r.dbType },
          { Metric: 'Database', Value: r.database },
          { Metric: 'Tables discovered', Value: r.tablesDiscovered },
          { Metric: 'Generation mode', Value: r.mode },
          { Metric: 'Records requested', Value: r.recordsRequested },
          { Metric: 'Records generated', Value: r.recordsGenerated },
          { Metric: 'Data-type validity %', Value: r.dataTypeValidity },
          { Metric: 'Relationship integrity %', Value: r.relationshipIntegrity },
          { Metric: 'Uniqueness violations', Value: r.uniquenessViolations },
          { Metric: 'Status', Value: r.status },
          { Metric: 'Duration (ms)', Value: r.durationMs },
        ]),
        'Summary',
      )
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(r.checks), 'Checks')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(r.perTable), 'Per table')
      if (r.scenarioCoverage) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(r.scenarioCoverage.map((c) => ({ Table: c.scenario.table, Column: c.scenario.column, Value: c.scenario.value, Requested: c.scenario.count, Generated: c.generated, Result: c.result, Note: c.note ?? '' }))), 'Scenario coverage')
      return { blob: wbBlob(wb), filename: `${stamp}_report.xlsx` }
    }
  }
}
