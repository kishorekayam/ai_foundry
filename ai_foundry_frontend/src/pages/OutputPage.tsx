// src/pages/OutputPage.tsx
import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Archive, Braces, Check, Database, Download, FileSpreadsheet, FileText, FlaskConical, ListChecks, Table2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Alert, Badge, Button, Card, CardHeader, PageHeader } from '../components/ui'
import { saveBlob } from '../lib/download'
import { useWorkflow } from '../store/workflow'
import type { ExportFormat } from '../types'

interface Item {
  id: ExportFormat | 'archive'
  title: string
  desc: string
  tag: string
  icon: typeof Download
  disabled?: string
}

export default function OutputPage() {
  const wf = useWorkflow()
  const nav = useNavigate()
  const schema = wf.schema!
  const mode = wf.config!.mode
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState<string>()
  const [confirming, setConfirming] = useState(false)
  const [approved, setApproved] = useState(false)

  const data: Item[] = [
    { id: 'xlsx', title: 'Excel (.xlsx)', desc: 'One workbook, one sheet per table', tag: 'MVP', icon: FileSpreadsheet },
    { id: 'csv-zip', title: 'CSV ZIP', desc: 'One CSV per table plus schema manifest and validation report', tag: 'MVP', icon: Archive },
    { id: 'json', title: 'JSON', desc: 'Grouped synthetic records', tag: 'MVP', icon: Braces },
    { id: 'sql-postgres', title: 'PostgreSQL .sql', desc: 'PostgreSQL-compatible import script', tag: 'MVP', icon: FileText, disabled: schema.dbType !== 'postgresql' ? 'Available for PostgreSQL schemas' : undefined },
    { id: 'sql-mysql', title: 'MySQL .sql', desc: 'MySQL-compatible import script', tag: 'MySQL phase', icon: FileText, disabled: schema.dbType !== 'mysql' ? 'Available for MySQL schemas' : undefined },
    { id: 'archive', title: 'Native database archive', desc: 'Genuine DB-specific backup from a disposable synthetic database', tag: 'Future', icon: Database, disabled: 'Planned for a later phase. A SQL script is not a pg_dump archive.' },
  ]
  const tests: Item[] = [
    { id: 'testcase-xlsx', title: 'Test case workbook', desc: 'Test IDs, endpoint, steps, request body and expected status, plus endpoint coverage', tag: 'Mode 3', icon: ListChecks },
    { id: 'postman', title: 'Postman Collection', desc: 'Your requests with positive, negative, boundary and workflow cases and status assertions (v2.1)', tag: 'Mode 3', icon: FlaskConical },
    { id: 'pytest', title: 'Pytest files', desc: 'httpx-based tests; set BASE_URL and AUTH_TOKEN, workflow tests chain the created id', tag: 'Optional', icon: FileText },
    { id: 'mapping-report', title: 'Endpoint coverage', desc: 'Cases per request and category, with the matched table', tag: 'Mode 3', icon: Table2 },
  ]
  const reports: Item[] = [
    { id: 'report-json', title: 'Report (JSON)', desc: 'Full validation and coverage report', tag: 'MVP', icon: Braces },
    { id: 'report-xlsx', title: 'Report (Excel)', desc: 'Summary, checks, per-table counts and coverage sheets', tag: 'MVP', icon: FileSpreadsheet },
  ]

  const download = async (f: ExportFormat) => {
    setBusy(f)
    setError(undefined)
    try {
      const file = await api.exportFile(wf.jobId!, f)
      saveBlob(file.blob, file.filename)
      wf.addDownload(file.filename)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(undefined)
    }
  }

  const targets = useQuery({ queryKey: ['targets'], queryFn: () => api.listTargets() })
  const target = targets.data?.find((t) => t.id === schema.targetId)
  const loadable = !!target?.loadAllowed
  const loadBlockedReason = !target
    ? 'Saved connection not found. Go back to Connect and test the connection again.'
    : schema.dbType !== 'postgresql'
      ? 'Direct load is available for PostgreSQL databases only (MySQL and MongoDB are planned). You can still download the files.'
      : 'This connection was saved without "allow loading". Go back to Connect, tick "This is a disposable test database. Allow loading…" and test the connection again. Only do this for a database you are happy to insert test rows into.'
  const plan = useQuery({ queryKey: ['loadplan', wf.jobId, target?.id], queryFn: () => api.getLoadPlan(wf.jobId!, target!.id), enabled: confirming && !!target })
  const load = useMutation({
    mutationFn: () => api.startLoad(wf.jobId!, target!.id),
    onSuccess: (r) => {
      wf.update({ loadId: r.loadId })
      nav('/result')
    },
  })

  const grid = (items: Item[]) => (
    <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((it) => (
        <div key={it.id} className={clsx('flex flex-col rounded-xl border p-4', it.disabled ? 'border-slate-200 bg-slate-50 opacity-80' : 'border-slate-200 bg-white')}>
          <div className="flex items-start justify-between">
            <it.icon className="size-6 text-react" />
            <Badge tone={it.tag === 'Future' ? 'gray' : 'blue'}>{it.tag}</Badge>
          </div>
          <div className="mt-2 text-sm font-semibold">{it.title}</div>
          <p className="mt-0.5 flex-1 text-xs text-slate-500">{it.disabled ?? it.desc}</p>
          <Button variant="secondary" className="mt-3" disabled={!!it.disabled} loading={busy === it.id} onClick={() => download(it.id as ExportFormat)}>
            {wf.downloads.some((d) => d.toLowerCase().includes(it.id.split('-')[0])) && <Check className="size-4 text-emerald-600" />}
            <Download className="size-4" /> Download
          </Button>
        </div>
      ))}
    </div>
  )

  if (confirming && target) {
    return (
      <div className="mx-auto max-w-2xl">
        <PageHeader title="Confirm database load" subtitle="Nothing is loaded without your approval. Review the target and counts." />
        <Card tone="boomi">
          <CardHeader title="Approved target environment" />
          <div className="space-y-4 p-5">
            <div className="rounded-lg bg-slate-50 p-4 text-sm">
              <div className="font-semibold">{target.label}</div>
              <div className="font-mono text-xs text-slate-600">{target.host}:{target.port}/{target.database}</div>
            </div>
            <div>
              <div className="mb-2 text-xs font-semibold text-slate-500">Affected tables, loaded parents first</div>
              <table className="w-full text-sm">
                <tbody className="divide-y divide-slate-100">
                  {plan.data?.tables.map((t) => <tr key={t.table}><td className="py-1.5">{t.table}</td><td className="py-1.5 text-right font-semibold">{t.expected.toLocaleString()} records</td></tr>)}
                  {plan.data && <tr><td className="py-2 font-semibold">Total</td><td className="py-2 text-right font-bold">{plan.data.tables.reduce((s, t) => s + t.expected, 0).toLocaleString()}</td></tr>}
                </tbody>
              </table>
              {plan.isLoading && <p className="text-sm text-slate-500">Preparing plan…</p>}
              {plan.error && <Alert tone="error">{(plan.error as Error).message}</Alert>}
            </div>
            <Alert tone="info">Orchestrated by Boomi Process B. The load is reported as successful only after counts and foreign keys are verified.</Alert>
            <label className="flex items-start gap-3 text-sm">
              <input type="checkbox" className="mt-1" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
              <span>I approve inserting these synthetic records into <b>{target.database}</b>.</span>
            </label>
            {load.error && <Alert tone="error">{(load.error as Error).message}</Alert>}
            <div className="flex gap-2">
              <Button variant="danger" disabled={!approved || !plan.data} loading={load.isPending} onClick={() => load.mutate()}>Approve and load</Button>
              <Button variant="secondary" onClick={() => { setConfirming(false); setApproved(false) }}>Cancel</Button>
            </div>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Choose output" subtitle={mode === 'testcase' ? 'Download the test cases as a Postman collection, Pytest files or a workbook.' : 'Download files or load approved records into the test database.'} actions={<Button variant="secondary" onClick={() => nav('/result')}>Finish</Button>} />
      {error && <Alert tone="error" title="Export failed">{error}</Alert>}
      {mode !== 'testcase' && (
        <Card>
          <CardHeader title="Generated data" />
          {grid(data)}
        </Card>
      )}
      {mode === 'testcase' && (
        <Card tone="ai">
          <CardHeader title="Test case deliverables" />
          {grid(tests)}
        </Card>
      )}
      {mode !== 'testcase' && (
        <Card>
          <CardHeader title="Reports" />
          {grid(reports)}
        </Card>
      )}
      {mode !== 'testcase' && <Card tone="boomi">
        <CardHeader title="Direct test database load" subtitle="Optional. Boomi Process B orchestrates the load and the Python adapter inserts parents first." />
        <div className="flex flex-wrap items-center gap-4 p-5">
          <Button variant="danger" disabled={!loadable} onClick={() => setConfirming(true)}><Database className="size-4" /> Review load</Button>
          <span className="text-sm text-slate-600">{loadable ? `Target: ${target!.label}${target!.schemaName ? ` (schema ${target!.schemaName})` : ''}` : loadBlockedReason}</span>
        </div>
      </Card>}
    </div>
  )
}
