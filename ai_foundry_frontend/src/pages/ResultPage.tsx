// src/pages/ResultPage.tsx
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Download } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge, SummaryStats } from '../components/ReportPanels'
import { Alert, Badge, Button, Card, CardHeader, PageHeader, Progress, Timeline } from '../components/ui'
import { useWorkflow } from '../store/workflow'

export default function ResultPage() {
  const wf = useWorkflow()
  const nav = useNavigate()
  const job = useQuery({ queryKey: ['job', wf.jobId], queryFn: () => api.getJob(wf.jobId!) })
  const load = useQuery({
    queryKey: ['load', wf.loadId],
    queryFn: () => api.getLoad(wf.loadId!),
    enabled: !!wf.loadId,
    refetchInterval: (q) => (q.state.data?.status === 'running' || !q.state.data ? 500 : false),
  })
  const j = job.data
  const r = j?.report
  const l = load.data
  if (!r) return <p className="text-sm text-slate-500">Loading result…</p>

  return (
    <div className="space-y-6">
      <PageHeader
        title="Final result"
        subtitle={wf.loadId ? 'Load status and readiness report.' : 'Your files are ready. Nothing was loaded into a database.'}
        actions={<><Button variant="secondary" onClick={() => nav('/output')}>Back to output</Button><Button onClick={() => { wf.reset(); nav('/connect') }}>Start new session</Button></>}
      />
      <SummaryStats r={r} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Downloaded files" right={<Badge tone="blue">{wf.downloads.length}</Badge>} />
          {wf.downloads.length ? (
            <ul className="divide-y divide-slate-100">
              {wf.downloads.map((d) => <li key={d} className="flex items-center gap-3 px-5 py-2.5 text-sm"><Download className="size-4 text-react" />{d}</li>)}
            </ul>
          ) : <p className="px-5 py-6 text-sm text-slate-500">No files downloaded yet. Go back to the output step to download.</p>}
        </Card>

        <Card tone={l ? 'boomi' : undefined}>
          <CardHeader title="Database load report" subtitle="Boomi Process B" right={l && <Badge tone={l.status === 'success' ? 'green' : l.status === 'failed' ? 'red' : 'blue'}>{l.status === 'success' ? 'SUCCESS' : l.status === 'failed' ? 'FAILED' : 'RUNNING'}</Badge>} />
          {!l ? <p className="px-5 py-6 text-sm text-slate-500">No load was requested.</p> : (
            <div className="space-y-4 p-4">
              <Timeline steps={l.steps} />
              <div className="space-y-2 rounded-lg bg-slate-50 p-3">
                {l.perTable.map((t) => (
                  <div key={t.table} className="grid grid-cols-[1fr_auto] items-center gap-x-3 text-xs">
                    <span className="font-medium">{t.table}</span>
                    <span>{t.inserted.toLocaleString()} / {t.expected.toLocaleString()} inserted{t.skipped ? `, ${t.skipped} skipped` : ''}{t.failedBatches ? `, ${t.failedBatches} failed batch(es)` : ''}</span>
                    <div className="col-span-2"><Progress value={((t.inserted + (t.skipped ?? 0)) / t.expected) * 100} tone="green" /></div>
                  </div>
                ))}
              </div>
              <dl className="grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-slate-500">Boomi status</dt><dd className="font-semibold">{l.boomiStatus}</dd></div>
                <div><dt className="text-slate-500">Counts match</dt><dd className="font-semibold">{l.status === 'running' ? '…' : l.verification.countsMatch ? 'Yes' : 'No'}</dd></div>
                <div><dt className="text-slate-500">Foreign keys valid</dt><dd className="font-semibold">{l.status === 'running' ? '…' : l.verification.fkValid ? 'Yes' : 'No'}</dd></div>
              </dl>
              {l.warnings && l.warnings.length > 0 && <Alert tone="warning" title="Some records were skipped"><ul className="list-disc pl-5">{l.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Alert>}
              {l.status === 'success' && <Alert tone="success" title="Load verified">Reported as successful only after expected and actual counts matched and foreign keys were checked.</Alert>}
              {l.status === 'failed' && <Alert tone="error" title="Load verification failed">The loaded data did not match the approved dataset.</Alert>}
            </div>
          )}
        </Card>
      </div>

      {j?.testCases && r.testCoverage && (
        <Card tone="ai">
          <CardHeader title="Test-readiness report" right={<StatusBadge status={r.status} />} />
          <div className="grid gap-4 p-5 text-sm sm:grid-cols-4">
            <div><div className="text-xs text-slate-500">Cases generated</div><div className="text-xl font-semibold">{r.testCoverage.total}</div></div>
            <div><div className="text-xs text-slate-500">Ready to export</div><div className="text-xl font-semibold text-emerald-700">{r.testCoverage.readyToExport}</div></div>
            <div><div className="text-xs text-slate-500">Requests covered</div><div className="text-xl font-semibold">{new Set(j.testCases.map((c) => c.endpoint)).size}</div></div>
            <div><div className="text-xs text-slate-500">Waiting on rules / API contract</div><div className="text-xl font-semibold text-amber-700">{r.testCoverage.needingRules}</div></div>
          </div>
          <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">This reports readiness to execute. It is not proof that the API passed these tests.</p>
        </Card>
      )}

      <Card>
        <div className="flex items-center gap-3 p-5 text-sm text-slate-600">
          <CheckCircle2 className="size-5 text-emerald-600" />
          Results come from actual generation and validation against the discovered schema, not preset success messages.
        </div>
      </Card>
    </div>
  )
}
