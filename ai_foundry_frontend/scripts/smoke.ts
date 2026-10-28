// scripts/smoke.ts
// Headless smoke test of the in-browser demo engine: npx tsx scripts/smoke.ts
import { mockApi as api } from '../src/api/mock/mockApi'
import type { JobConfig } from '../src/types'

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function run(label: string, config: JobConfig) {
  const schema = await api.fetchSchema('pg-placement-test')
  const { jobId } = await api.createJob(schema, config)
  let job = await api.getJob(jobId)
  while (job.status === 'running') {
    await wait(300)
    job = await api.getJob(jobId)
  }
  const r = job.report!
  console.log(`\n== ${label}: ${job.status} | ${r.recordsGenerated}/${r.recordsRequested} records`)
  for (const c of r.checks) console.log(`  ${c.status.padEnd(7)} ${c.label} - ${c.detail}`)
  r.adjustments.forEach((a) => console.log('  adjustment:', a))
  r.scenarioCoverage?.forEach((c) => console.log(`  scenario ${c.scenario.count} ${c.scenario.value} ${c.scenario.table}: ${c.generated} ${c.result}`))
  if (r.testCoverage) console.log('  tests:', JSON.stringify(r.testCoverage))
  return { jobId, job }
}

const tables = (n: number) => ['universities', 'departments', 'students', 'placement_providers', 'supervisors', 'placements', 'timesheets', 'timesheet_reviews'].map((t) => ({ table: t, count: t === 'timesheets' ? n : t === 'timesheet_reviews' ? 0 : 20 }))

const fast = await run('Fast', { mode: 'fast', locale: 'en_IN', seed: 42, tables: tables(200) })
const p = await api.getPreview(fast.jobId, 'timesheets', 0, 3)
console.log(p.rows)

const sc = await run('Scenario', { mode: 'scenario', locale: 'en_IN', tables: tables(40), description: 'An Indian university placement app. Generate 30 approved timesheets, 10 pending timesheets, 5 rejected timesheets and 5 queried timesheets' })
const after = await api.generateMissing(sc.jobId)
console.log('after generateMissing:', after.status, after.report!.scenarioCoverage!.map((c) => `${c.scenario.value}:${c.generated}/${c.scenario.count} ${c.result}`).join(', '))

const tc = await run('TestCase', { mode: 'testcase', locale: 'en_IN', tables: [], testCase: { feature: 'Generate positive, negative and workflow test cases for student timesheet submission and supervisor approval', categories: ['positive', 'negative', 'boundary', 'workflow'] } })
for (const t of tc.job.testCases!) console.log(`  ${t.id} [${t.category}] ${t.title} -> ${t.expected} | prereq: ${t.prerequisiteRecords.map((x) => x.table + ':' + x.key).join(',')} ${t.ready ? '' : '(needs rules)'}`)
for (const f of ['xlsx', 'csv-zip', 'json', 'sql-postgres', 'testcase-xlsx', 'pytest', 'report-xlsx'] as const) {
  const x = await api.exportFile(tc.jobId, f)
  console.log('export', f, x.filename, x.blob.size)
}
const { loadId } = await api.startLoad(fast.jobId, 'pg-placement-test')
await wait(11000)
const l = await api.getLoad(loadId)
console.log('load', l.status, l.boomiStatus, l.verification)
process.exit(0)
