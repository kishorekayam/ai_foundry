// src/components/ReportPanels.tsx
import { useMutation } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, ChevronDown, MinusCircle, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import type { Job, Report, TestCase, TestCategory, ValidationCheck } from '../types'
import { Alert, Badge, Button, Card, CardHeader, Stat } from './ui'

export function StatusBadge({ status }: { status: Report['status'] }) {
  return <Badge tone={status === 'completed' ? 'green' : status === 'partial' ? 'amber' : 'red'}>{status === 'partial' ? 'partially completed' : status}</Badge>
}

export function SummaryStats({ r }: { r: Report }) {
  if (r.mode === 'testcase' && r.testCoverage) {
    const by = r.testCoverage.byCategory
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Status" value={<StatusBadge status={r.status} />} sub={`${(r.durationMs / 1000).toFixed(1)}s`} />
        <Stat label="Test cases" value={r.testCoverage.total} sub={`${r.testCoverage.readyToExport} ready to run`} />
        <Stat label="By category" value={`${by.positive} / ${by.negative} / ${by.boundary} / ${by.workflow}`} sub="positive / negative / boundary / workflow" />
        <Stat label="Records written to your database" value={0} tone="green" sub="none generated, none loaded" />
      </div>
    )
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
      <Stat label="Generation status" value={<StatusBadge status={r.status} />} sub={`${(r.durationMs / 1000).toFixed(1)}s`} />
      <Stat label="Records generated" value={r.recordsGenerated.toLocaleString()} sub={`of ${r.recordsRequested.toLocaleString()} requested`} tone={r.recordsGenerated < r.recordsRequested ? 'amber' : undefined} />
      <Stat label="Data-type validity" value={`${r.dataTypeValidity}%`} tone={r.dataTypeValidity === 100 ? 'green' : 'red'} />
      <Stat label="Relationship integrity" value={`${r.relationshipIntegrity}%`} tone={r.relationshipIntegrity === 100 ? 'green' : 'red'} />
      <Stat label="Uniqueness violations" value={r.uniquenessViolations} tone={r.uniquenessViolations === 0 ? 'green' : 'red'} />
    </div>
  )
}

function CheckIcon({ s }: { s: ValidationCheck['status'] }) {
  if (s === 'passed') return <CheckCircle2 className="size-5 text-emerald-600" />
  if (s === 'warning') return <AlertTriangle className="size-5 text-amber-600" />
  if (s === 'failed') return <XCircle className="size-5 text-red-600" />
  return <MinusCircle className="size-5 text-slate-300" />
}

export function ReportView({ r }: { r: Report }) {
  const rows: [string, string | number][] = [
    ['Database type', r.dbType],
    ['Database', r.database],
    ['Tables discovered', r.tablesDiscovered],
    ['Generation mode', { fast: 'Fast Test', scenario: 'AI Realistic & Scenario', testcase: 'AI Test Case Generator' }[r.mode]],
    ...(r.mode === 'testcase' ? [] : ([['Records requested', r.recordsRequested], ['Records generated', r.recordsGenerated]] as [string, number][])),
    ['Execution duration', `${(r.durationMs / 1000).toFixed(2)} s`],
  ]
  return (
    <div className="space-y-6">
      {r.adjustments.length > 0 && (
        <Alert tone="warning" title={r.mode === 'testcase' ? 'Notes' : 'Requested counts could not be met exactly'}>
          <ul className="list-disc pl-5">{r.adjustments.map((a) => <li key={a}>{a}</li>)}</ul>
        </Alert>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Validation checks" subtitle={r.mode === 'testcase' ? 'Run against your collection and the database rules' : 'Run against the generated dataset before any insert is offered'} />
          <ul className="divide-y divide-slate-100">
            {r.checks.map((c) => (
              <li key={c.id} className="flex items-center gap-3 px-5 py-2.5">
                <CheckIcon s={c.status} />
                <div className="flex-1">
                  <div className="text-sm font-medium">{c.label}</div>
                  <div className="text-xs text-slate-500">{c.detail}</div>
                </div>
                <span className={clsx('text-xs font-semibold', c.status === 'passed' ? 'text-emerald-700' : c.status === 'skipped' ? 'text-slate-400' : c.status === 'warning' ? 'text-amber-700' : 'text-red-700')}>{c.status === 'passed' ? 'Passed' : c.status === 'skipped' ? 'N/A' : c.status === 'warning' ? 'Warning' : 'Failed'}</span>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-6">
          {r.mode !== 'testcase' && <Card>
            <CardHeader title="Requested vs generated" />
            <div className="h-64 p-3">
              <ResponsiveContainer>
                <BarChart data={r.perTable} margin={{ left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="table" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={55} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="requested" fill="#c5cad8" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="generated" fill="#0f52ba" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>}
          <Card>
            <CardHeader title="Report details" />
            <dl className="divide-y divide-slate-100 text-sm">
              {rows.map(([k, v]) => (
                <div key={k} className="flex justify-between px-5 py-2"><dt className="text-slate-500">{k}</dt><dd className="font-medium">{v}</dd></div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
      <Card>
        <CardHeader title="Unsupported constraints" subtitle="Rules that are not automatically validated or could not be discovered" />
        {r.unsupportedConstraints.length ? <ul className="list-disc space-y-1 px-9 py-4 text-sm text-slate-700">{r.unsupportedConstraints.map((u) => <li key={u}>{u}</li>)}</ul> : <p className="px-5 py-4 text-sm text-slate-500">None.</p>}
      </Card>
    </div>
  )
}

export function ScenarioView({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const cov = job.report!.scenarioCoverage ?? []
  const gen = useMutation({ mutationFn: () => api.generateMissing(job.id), onSuccess: onChanged })
  const missing = cov.some((c) => c.result === 'Missing' || c.result === 'Partial')
  const tone = { Covered: 'green', Partial: 'amber', Missing: 'red', Unsupported: 'gray' } as const
  return (
    <Card tone="ai">
      <CardHeader
        title="Scenario coverage report"
        subtitle="Requested workflow scenarios against records actually generated"
        right={missing && <Button onClick={() => gen.mutate()} loading={gen.isPending}>Generate missing scenarios</Button>}
      />
      {cov.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-500">No explicit scenarios were requested. Realistic data was generated for the described domain.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr><th className="px-5 py-2">Requested scenario</th><th className="px-3 py-2">Requested</th><th className="px-3 py-2">Generated</th><th className="px-3 py-2">Result</th><th className="px-3 py-2">Note</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {cov.map((c, i) => (
              <tr key={i}>
                <td className="px-5 py-2.5 font-medium">{c.scenario.value.charAt(0) + c.scenario.value.slice(1).toLowerCase()} {c.scenario.table.replace(/_/g, ' ')}</td>
                <td className="px-3 py-2.5">{c.scenario.count}</td>
                <td className="px-3 py-2.5">{c.generated}</td>
                <td className="px-3 py-2.5"><Badge tone={tone[c.result]}>{c.result}</Badge></td>
                <td className="px-3 py-2.5 text-xs text-slate-500">{c.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {gen.isError && <div className="p-4"><Alert tone="error">{(gen.error as Error).message}</Alert></div>}
    </Card>
  )
}

const catTone: Record<TestCategory, 'green' | 'red' | 'amber' | 'blue'> = { positive: 'green', negative: 'red', boundary: 'amber', workflow: 'blue' }

function statusOf(r: { expectedStatus?: string }) {
  return r.expectedStatus ?? '2xx'
}

function CaseRow({ tc }: { tc: TestCase }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-slate-50">
        <span className="w-14 font-mono text-xs font-semibold">{tc.id}</span>
        <Badge tone={catTone[tc.category]}>{tc.category}</Badge>
        <span className="flex-1 text-sm">{tc.title}</span>
        {tc.endpoint && <span className="hidden font-mono text-[11px] text-slate-500 lg:inline">{tc.endpoint}</span>}
        <Badge tone={tc.ready ? 'green' : 'amber'}>{tc.ready ? 'Ready' : 'Needs rules'}</Badge>
        <ChevronDown className={clsx('size-4 text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="grid gap-4 bg-slate-50 px-5 py-4 text-sm md:grid-cols-3">
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-500">Preconditions</div>
            <ul className="list-disc pl-4">{tc.preconditions.length ? tc.preconditions.map((p) => <li key={p}>{p}</li>) : <li>None</li>}</ul>
            <div className="mb-1 mt-3 text-xs font-semibold text-slate-500">Steps</div>
            <ol className="list-decimal pl-4">{tc.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-500">Expected result</div>
            <p>{tc.expected}</p>
            <p className="mt-2 text-xs text-slate-500">{tc.readinessNote}</p>
            {tc.table && <p className="mt-2 text-xs text-slate-500">Field rules from table <span className="font-mono">{tc.table}</span></p>}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-slate-500">{tc.requests?.length ? 'Requests (in order)' : 'Request'}</div>
            {(tc.requests?.length ? tc.requests : tc.fixture ? [tc.fixture] : []).map((r, i) => (
              <pre key={i} className="mb-2 max-h-40 overflow-auto rounded bg-white p-2 font-mono text-[10px] scroll-thin">{r.method} {r.path}  {'->'} expect {statusOf(r)}{r.body ? '\n' + JSON.stringify(r.body, null, 1) : ''}</pre>
            ))}
          </div>
        </div>
      )}
    </li>
  )
}

export function TestCaseView({ job }: { job: Job }) {
  const cov = job.report!.testCoverage!
  const cases = job.testCases ?? []
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <Card tone="ai">
          <CardHeader title="Test case coverage report" />
          <table className="w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {(Object.keys(cov.byCategory) as TestCategory[]).map((k) => (
                <tr key={k}><td className="px-5 py-2 capitalize">{k} tests</td><td className="px-5 py-2 text-right font-semibold">{cov.byCategory[k]}</td></tr>
              ))}
              <tr className="bg-slate-50"><td className="px-5 py-2 font-semibold">Total</td><td className="px-5 py-2 text-right font-bold">{cov.total}</td></tr>
            </tbody>
          </table>
          <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">Generated-test count is not code coverage and is not proof that an API passed these tests. Expected statuses are 2xx / 4xx classes unless your collection documents an exact code.</p>
        </Card>
        <div className="grid content-start gap-4 sm:grid-cols-3">
          <Stat label="Requests covered" value={new Set(cases.map((c) => c.endpoint)).size} sub={`${cases.filter((c) => c.requests?.length).length} multi-step workflows`} />
          <Stat label="Ready to export" value={cov.readyToExport} tone="green" />
          <Stat label="Need rules / API contract" value={cov.needingRules} tone={cov.needingRules ? 'amber' : 'green'} sub="schema alone cannot define expected behaviour" />
        </div>
      </div>
      <Card>
        <CardHeader title="Generated test cases" subtitle="Expand a case to see its steps, expected status and the exact request" />
        <ul className="divide-y divide-slate-100">{cases.map((t) => <CaseRow key={t.id} tc={t} />)}</ul>
      </Card>
    </div>
  )
}
