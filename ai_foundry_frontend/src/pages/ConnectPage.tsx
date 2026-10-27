import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Database, KeyRound, Lock, Plug } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Alert, Button, Card, CardHeader, Field, Input, LayerBadge, PageHeader, Select, Timeline } from '../components/ui'
import { useWorkflow } from '../store/workflow'
import type { ConnectionRequest, ConnectionResult, DbType, StepState } from '../types'

const DB: { id: DbType; label: string; port: number; note?: string; color: string; disabled?: boolean }[] = [
  { id: 'postgresql', label: 'PostgreSQL', port: 5432, color: '#336791' },
  { id: 'mysql', label: 'MySQL', port: 3306, note: 'Next phase', color: '#c77b0b' },
  { id: 'mongodb', label: 'MongoDB', port: 27017, note: 'Coming soon', color: '#2f8f4e', disabled: true },
]

const PROCESS_A = [
  { id: 'auth', layer: 'FastAPI', label: 'Authenticate user and validate destination against approved network policy' },
  { id: 'recv', layer: 'Boomi', label: 'Web Services Server receives metadata request (target ID, no credentials)' },
  { id: 'valid', layer: 'Boomi', label: 'Validate request and target, reject unapproved targets' },
  { id: 'route', layer: 'Boomi', label: 'Route by database type' },
  { id: 'meta', layer: 'Database', label: 'Read metadata only: information_schema / PyMongo validators. No rows are read' },
  { id: 'norm', layer: 'Boomi', label: 'Normalize metadata JSON and return to FastAPI' },
  { id: 'store', layer: 'FastAPI', label: 'Normalize and store unified schema model for the job' },
]

export default function ConnectPage() {
  const nav = useNavigate()
  const wf = useWorkflow()
  const [dbType, setDbType] = useState<DbType>('postgresql')
  const [source, setSource] = useState<'registered' | 'manual'>('manual')
  const [targetId, setTargetId] = useState<string>()
  const [label, setLabel] = useState('')
  const [pgSchema, setPgSchema] = useState('public')
  const [allowLoad, setAllowLoad] = useState(false)
  const [f, setF] = useState({ host: '', port: '5432', database: '', username: '', password: '', ssl: 'prefer' as 'disable' | 'require' | 'verify-full', uri: '' })
  const [result, setResult] = useState<ConnectionResult>()
  const [steps, setSteps] = useState<{ id: string; layer: string; label: string; state: StepState }[]>()
  const timer = useRef<number>(0)

  const targets = useQuery({ queryKey: ['targets'], queryFn: () => api.listTargets() })
  const forType = targets.data?.filter((t) => t.dbType === dbType) ?? []
  const target = forType.find((t) => t.id === targetId)

  // Changing the database type resets the form and any earlier result.
  useEffect(() => {
    setResult(undefined)
    setF((p) => ({ ...p, port: String(DB.find((d) => d.id === dbType)!.port), password: '' }))
  }, [dbType])

  // A refreshed saved-connections list (e.g. right after a successful test) must not wipe the test result.
  useEffect(() => {
    setTargetId((cur) => (cur && forType.some((t) => t.id === cur) ? cur : forType[0]?.id))
    if (!forType.length) setSource('manual')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dbType, targets.data])

  useEffect(() => () => window.clearInterval(timer.current), [])

  const test = useMutation({
    mutationFn: (r: ConnectionRequest) => api.testConnection(r),
    onSuccess: (r) => {
      setResult(r)
      if (r.ok) void targets.refetch()
      setF((p) => ({ ...p, password: '', uri: '' })) // never keep secrets in component state after use
    },
    onError: (e: Error) => setResult({ ok: false, dbType, database: '', metadataAccess: 'Denied', tablesDiscovered: 0, message: e.message }),
  })

  const extract = useMutation({
    mutationFn: async () => {
      setSteps(PROCESS_A.map((s) => ({ ...s, state: 'pending' as StepState })))
      let i = 0
      timer.current = window.setInterval(() => {
        setSteps((prev) => prev?.map((s, k) => ({ ...s, state: k < i ? 'done' : k === i ? 'running' : 'pending' })))
        if (i < PROCESS_A.length - 1) i++
      }, 300)
      try {
        return await api.fetchSchema(result!.targetId!)
      } finally {
        window.clearInterval(timer.current)
      }
    },
    onSuccess: async (schema) => {
      setSteps((p) => p?.map((s) => ({ ...s, state: 'done' as StepState })))
      wf.update({ schema, connection: result, config: undefined, jobId: undefined, mode: undefined, downloads: [], loadId: undefined })
      await new Promise((r) => setTimeout(r, 400))
      nav('/schema')
    },
    onError: () => setSteps((p) => p?.map((s) => (s.state === 'running' ? { ...s, state: 'failed' as StepState } : s))),
  })

  const submit = () => {
    setResult(undefined)
    setSteps(undefined)
    if (source === 'registered' && targetId) return test.mutate({ dbType, targetId })
    if (dbType === 'mongodb') return test.mutate({ dbType, uri: f.uri, label: label || undefined })
    test.mutate({ dbType, host: f.host, port: Number(f.port), database: f.database, username: f.username, password: f.password, ssl: f.ssl, label: label || undefined, allowLoad, schema: dbType === 'postgresql' ? pgSchema.trim() || 'public' : undefined })
  }

  const manual = source === 'manual'
  const canSubmit = manual ? (dbType === 'mongodb' ? !!f.uri : !!(f.host && f.database && f.username)) : !!targetId

  return (
    <div>
      <PageHeader title="Connect a database" subtitle="Choose a database type and test the connection. Only schema metadata is read; no existing rows are retrieved." />
      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Card tone="react">
            <CardHeader title="Database type" right={<LayerBadge layer="React" />} />
            <div className="grid gap-3 p-5 sm:grid-cols-3">
              {DB.map((d) => (
                <button key={d.id} disabled={d.disabled} title={d.disabled ? 'Not available yet' : undefined} onClick={() => setDbType(d.id)} className={clsx('rounded-xl border-2 p-4 text-left transition-colors', d.disabled ? 'cursor-not-allowed border-slate-200 opacity-50' : dbType === d.id ? 'border-react bg-react-soft' : 'border-slate-200 hover:border-slate-300')}>
                  <Database className="size-6" style={{ color: d.color }} />
                  <div className="mt-2 text-sm font-semibold">{d.label}</div>
                  <div className="text-xs text-slate-500">{d.note ?? 'MVP primary target'}</div>
                </button>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Connection details"
              subtitle="Enter your own test database. Credentials are used to connect, then stored encrypted on the server. Only a connection id comes back to the browser."
              right={
                <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs font-semibold">
                  {(['registered', 'manual'] as const).map((s) => (
                    <button key={s} onClick={() => { setSource(s); setResult(undefined) }} className={clsx('rounded-md px-3 py-1.5', source === s ? 'bg-white shadow-sm' : 'text-slate-500')}>
                      {s === 'registered' ? 'Saved connections' : 'New connection'}
                    </button>
                  ))}
                </div>
              }
            />
            <div className="space-y-4 p-5">
              {!manual ? (
                forType.length ? (
                  <div className="space-y-2">
                    {forType.map((t) => (
                      <button key={t.id} onClick={() => setTargetId(t.id)} className={clsx('flex w-full items-center gap-3 rounded-lg border p-3 text-left', targetId === t.id ? 'border-react bg-react-soft/50' : 'border-slate-200 hover:bg-slate-50')}>
                        <KeyRound className="size-5 text-slate-500" />
                        <div className="flex-1">
                          <div className="text-sm font-semibold">{t.label}</div>
                          <div className="font-mono text-xs text-slate-500">{t.host}:{t.port}/{t.database}{t.schemaName && t.schemaName !== 'public' ? ` (schema ${t.schemaName})` : ''}</div>
                        </div>
                        <span className="text-xs text-slate-500">credentials held server-side</span>
                        {api.deleteTarget && <span role="button" title="Remove" onClick={async (e) => { e.stopPropagation(); await api.deleteTarget!(t.id); void targets.refetch() }} className="ml-2 text-xs text-boomi hover:underline">Remove</span>}
                      </button>
                    ))}
                  </div>
                ) : (
                  <Alert tone="info">No saved connection for this database type yet. Use "New connection".</Alert>
                )
              ) : dbType === 'mongodb' ? (
                <Field label="Connection URI" hint="Example: mongodb://host:27017/dbname. Used once for the test and never stored or logged.">
                  <Input type="password" autoComplete="off" value={f.uri} onChange={(e) => setF({ ...f, uri: e.target.value })} placeholder="mongodb://user:password@host:27017/database" />
                </Field>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Hostname"><Input value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} placeholder="db.example.com" /></Field>
                  <Field label="Port"><Input type="number" value={f.port} onChange={(e) => setF({ ...f, port: e.target.value })} /></Field>
                  <Field label="Database name"><Input value={f.database} onChange={(e) => setF({ ...f, database: e.target.value })} placeholder="placement_test_db" /></Field>
                  {dbType === 'postgresql' && (
                    <Field label="Schema" hint="Tables are read from and loaded into this schema only."><Input value={pgSchema} onChange={(e) => setPgSchema(e.target.value)} placeholder="public" /></Field>
                  )}
                  <Field label="SSL mode">
                    <Select value={f.ssl} onChange={(e) => setF({ ...f, ssl: e.target.value as typeof f.ssl })}>
                      <option value="disable">Disable</option>
                      <option value="require">Require</option>
                      <option value="verify-full">Verify full certificate</option>
                    </Select>
                  </Field>
                  <Field label="Username"><Input autoComplete="off" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
                  <Field label="Password"><Input type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
                </div>
              )}
              {manual && (
                <>
                  <Field label="Connection name (optional)"><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Placement test DB" /></Field>
                  {dbType === 'postgresql' && (
                    <label className="flex items-start gap-2 text-sm text-slate-700">
                      <input type="checkbox" className="mt-1" checked={allowLoad} onChange={(e) => setAllowLoad(e.target.checked)} />
                      <span>This is a disposable test database. Allow loading generated data into it (you still approve every load).</span>
                    </label>
                  )}
                  <Alert tone="info">Destinations are checked by the network policy: private networks and cloud-metadata addresses are refused. Use a database reachable from the internet.</Alert>
                </>
              )}
              <div className="flex items-center gap-3">
                <Button onClick={submit} loading={test.isPending} disabled={!canSubmit}>
                  <Plug className="size-4" /> Test connection
                </Button>
                {target && !manual && <span className="text-xs text-slate-500">Target: {target.database}</span>}
              </div>
            </div>
          </Card>

          {result && (
            <Card tone={result.ok ? 'react' : 'boomi'}>
              <CardHeader title="Test result" />
              <div className="p-5">
                {result.ok ? (
                  <>
                    <pre className="rounded-lg bg-python p-4 font-mono text-sm leading-relaxed text-emerald-200">{`Database Type: ${DB.find((d) => d.id === result.dbType)!.label}
Database Name: ${result.database}

Connection Status: Successful
Metadata Access: ${result.metadataAccess}
Tables Discovered: ${result.tablesDiscovered}`}</pre>
                    <div className="mt-4 flex items-center gap-3">
                      <Button onClick={() => extract.mutate()} loading={extract.isPending}>Extract schema via Boomi</Button>
                      <span className="text-xs text-slate-500">Metadata only. No row data is read.</span>
                    </div>
                  </>
                ) : (
                  <Alert tone="error" title="Connection failed">{result.message}</Alert>
                )}
              </div>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          {steps ? (
            <Card tone="boomi">
              <CardHeader title="Boomi Process A: schema metadata extraction" subtitle="Live progress of the metadata workflow" />
              <div className="p-2">
                <Timeline steps={steps} />
              </div>
              {extract.isError && <div className="p-4 pt-0"><Alert tone="error">{(extract.error as Error).message}</Alert></div>}
            </Card>
          ) : (
            <Card>
              <CardHeader title="What happens next" />
              <ol className="space-y-3 p-5 text-sm text-slate-600">
                {PROCESS_A.slice(0, 5).map((s, i) => (
                  <li key={s.id} className="flex gap-3">
                    <span className="grid size-6 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-bold">{i + 1}</span>
                    <span>{s.label}</span>
                  </li>
                ))}
              </ol>
            </Card>
          )}
          <Card>
            <div className="flex gap-3 p-5 text-sm text-slate-600">
              <Lock className="size-5 shrink-0 text-emerald-600" />
              <p>Credentials are never included in AI prompts, frontend logs or ordinary Boomi documents. After a test they are cleared from the form.</p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
