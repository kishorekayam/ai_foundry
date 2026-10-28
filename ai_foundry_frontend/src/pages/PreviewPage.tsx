// src/pages/PreviewPage.tsx
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import DataPreview from '../components/DataPreview'
import { ReportView, ScenarioView, SummaryStats, TestCaseView } from '../components/ReportPanels'
import { Alert, Button, PageHeader, Tabs } from '../components/ui'
import { useWorkflow } from '../store/workflow'

type Tab = 'data' | 'scenarios' | 'tests' | 'report'

export default function PreviewPage() {
  const wf = useWorkflow()
  const nav = useNavigate()
  const qc = useQueryClient()
  const mode = wf.config!.mode
  const [tab, setTab] = useState<Tab>(mode === 'testcase' ? 'tests' : 'data')
  const [openTable] = useState<string>()
  const job = useQuery({ queryKey: ['job', wf.jobId], queryFn: () => api.getJob(wf.jobId!) })
  const j = job.data

  if (job.error) return <Alert tone="error" title="Job unavailable">{(job.error as Error).message}</Alert>
  if (!j?.report) return <p className="text-sm text-slate-500">Loading report…</p>
  const r = j.report

  const tabs: { id: Tab; label: string }[] = [
    ...(mode !== 'testcase' ? [{ id: 'data' as const, label: 'Data preview' }] : []),
    ...(mode === 'scenario' ? [{ id: 'scenarios' as const, label: 'Scenario coverage' }] : []),
    ...(mode === 'testcase' ? [{ id: 'tests' as const, label: 'Test cases' }] : []),
    ...(mode !== 'testcase' ? [{ id: 'report' as const, label: 'Quality report' }] : []),
  ]
  const order: Tab[] = mode === 'testcase' ? ['tests'] : tabs.map((t) => t.id)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Preview & validate"
        subtitle={mode === 'testcase' ? 'Review the generated test cases and their requests, then export them.' : 'Review 20 records per table, the validation results and coverage before choosing an output.'}
        actions={<Button onClick={() => nav('/output')} disabled={r.status === 'failed'}>Choose output</Button>}
      />
      {r.status === 'failed' && <Alert tone="error" title="Validation failed">Fix the failing checks and regenerate. Export and load are disabled.</Alert>}
      <SummaryStats r={r} />
      {mode !== 'testcase' && <Tabs tabs={order.map((o) => tabs.find((t) => t.id === o)!)} value={tab} onChange={setTab} />}
      {tab === 'data' && <DataPreview job={j} schema={wf.schema!} initialTable={openTable} />}
      {tab === 'scenarios' && <ScenarioView job={j} onChanged={() => qc.invalidateQueries({ queryKey: ['job', wf.jobId] })} />}
      {tab === 'tests' && r.testCoverage && <TestCaseView job={j} />}
      {tab === 'report' && <ReportView r={r} />}
    </div>
  )
}
