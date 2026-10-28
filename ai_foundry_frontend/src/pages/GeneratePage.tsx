// src/pages/GeneratePage.tsx
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Alert, Badge, Button, Card, CardHeader, PageHeader, Progress, Timeline } from '../components/ui'
import { useWorkflow } from '../store/workflow'

export default function GeneratePage() {
  const wf = useWorkflow()
  const nav = useNavigate()
  const started = useRef(false)
  const [err, setErr] = useState<string>()

  useEffect(() => {
    if (wf.jobId || started.current) return
    started.current = true
    api.createJob(wf.schema!, wf.config!).then((r) => wf.update({ jobId: r.jobId })).catch((e: Error) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const job = useQuery({
    queryKey: ['job', wf.jobId],
    queryFn: () => api.getJob(wf.jobId!),
    enabled: !!wf.jobId,
    refetchInterval: (q) => (q.state.data?.status === 'running' || !q.state.data ? 400 : false),
  })
  const j = job.data
  const done = j && j.status !== 'running'
  const pct = j ? (j.stages.filter((s) => s.state === 'done').length / j.stages.length) * 100 : 0

  useEffect(() => {
    if (done && j.status !== 'failed') {
      const t = setTimeout(() => nav('/preview'), 1200)
      return () => clearTimeout(t)
    }
  }, [done, j?.status, nav])

  const modeName = { fast: 'Fast Test', scenario: 'AI Realistic & Scenario', testcase: 'AI Test Case Generator' }[wf.config!.mode]

  return (
    <div>
      <PageHeader title="Generating" subtitle={`${modeName}. AI plans, Python creates and validates. Nothing is written to a database at this stage.`} />
      {(err || job.error) && <div className="mb-4"><Alert tone="error" title="Generation could not start">{err ?? (job.error as Error).message}</Alert></div>}
      <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
        <Card>
          <CardHeader title={j ? `Job ${j.id}` : 'Starting job…'} right={j && <Badge tone={j.status === 'running' ? 'blue' : j.status === 'failed' ? 'red' : j.status === 'partial' ? 'amber' : 'green'}>{j.status}</Badge>} />
          <div className="space-y-4 p-4">
            <Progress value={pct} tone={done ? 'green' : 'blue'} />
            {j && <Timeline steps={j.stages as never} />}
            {j?.error && <Alert tone="error">{j.error}</Alert>}
          </div>
        </Card>
        <div className="space-y-6">
          {j?.blueprint && (
            <Card tone="ai">
              <CardHeader title="AI generation blueprint" subtitle="Structured JSON returned by the model and validated by Python" />
              <pre className="max-h-96 overflow-auto bg-slate-50 p-4 font-mono text-[11px] leading-relaxed scroll-thin">{JSON.stringify(j.blueprint, null, 2)}</pre>
            </Card>
          )}
          {done && j.status !== 'failed' && (
            <Alert tone="success" title="Generation finished">Opening the preview and validation report…</Alert>
          )}
          {done && (
            <div className="flex gap-2">
              <Button onClick={() => nav('/preview')}>Open preview</Button>
              <Button variant="secondary" onClick={() => nav('/mode')}>Back to mode</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
