import { useMutation } from '@tanstack/react-query'
import clsx from 'clsx'
import { FlaskConical, Sparkles, Upload, Zap } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { LOCALES } from '../api/mock/engine'
import { Alert, Badge, Button, Card, CardHeader, Field, Input, LayerBadge, PageHeader, Select, Textarea } from '../components/ui'
import { useWorkflow } from '../store/workflow'
import type { Blueprint, GenMode, JobConfig, ParsedCollection, Schema, TestCategory } from '../types'

const MODES: { id: GenMode; title: string; tag: string; tagLayer: string; icon: typeof Zap; points: string[]; accent: string }[] = [
  { id: 'fast', title: 'Fast Test', tag: 'Schema only', tagLayer: 'Python', icon: Zap, accent: 'border-python', points: ['Schema-valid dummy records', 'No application description needed', 'Works even if the AI service is unavailable'] },
  { id: 'scenario', title: 'AI Realistic & Scenario', tag: 'Primary AI', tagLayer: 'AI', icon: Sparkles, accent: 'border-ai', points: ['Domain-specific, interconnected data', 'Optional exact scenarios, statuses and counts', 'AI plans the rules, Python generates'] },
  { id: 'testcase', title: 'AI Test Case Generator', tag: 'AI + tests', tagLayer: 'AI', icon: FlaskConical, accent: 'border-ai', points: ['Drop your Postman collection or OpenAPI file', 'Cases use your real endpoints, no data is loaded', 'Outputs: Postman, Pytest, Excel'] },
]

const CATS: { id: TestCategory; label: string }[] = [
  { id: 'positive', label: 'Positive' },
  { id: 'negative', label: 'Negative' },
  { id: 'boundary', label: 'Boundary' },
  { id: 'workflow', label: 'Workflow' },
]

function defaultCounts(schema: Schema) {
  const depth = new Map<string, number>()
  const d = (name: string, stack: string[] = []): number => {
    if (depth.has(name)) return depth.get(name)!
    const t = schema.tables.find((x) => x.name === name)!
    const ps = t.foreignKeys.filter((f) => f.refTable !== name && !stack.includes(f.refTable))
    const v = ps.length ? Math.max(...ps.map((p) => d(p.refTable, [...stack, name]))) + 1 : 0
    depth.set(name, v)
    return v
  }
  return Object.fromEntries(schema.tables.map((t) => [t.name, t.needsDefinition && t.columns.length <= 1 ? 0 : [10, 50, 100][Math.min(d(t.name), 2)]]))
}

export default function ModePage() {
  const wf = useWorkflow()
  const nav = useNavigate()
  const schema = wf.schema!
  const [mode, setMode] = useState<GenMode>(wf.mode ?? 'fast')
  const [counts, setCounts] = useState<Record<string, number>>(() => defaultCounts(schema))
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() => Object.fromEntries(schema.tables.map((t) => [t.name, !(t.needsDefinition && t.columns.length <= 1)])))
  const [locale, setLocale] = useState('en_IN')
  const [seed, setSeed] = useState('')
  const [description, setDescription] = useState('')
  const [advanced, setAdvanced] = useState('')
  const [feature, setFeature] = useState('')
  const [cats, setCats] = useState<TestCategory[]>(['positive', 'negative', 'boundary', 'workflow'])
  const [rules, setRules] = useState('')
  const [specText, setSpecText] = useState('')
  const [spec, setSpec] = useState<ParsedCollection>()
  const [specErr, setSpecErr] = useState<string>()
  const [useSamples, setUseSamples] = useState(false)
  const [baseUrl, setBaseUrl] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [bp, setBp] = useState<Blueprint>()

  const text = [description, advanced].filter((s) => s.trim()).join('. ')
  const tableList = schema.tables.map((t) => ({ table: t.name, count: enabled[t.name] ? Number(counts[t.name]) || 0 : 0 }))

  const config = useMemo<JobConfig>(
    () => ({
      mode,
      tables: tableList,
      locale,
      seed: seed.trim() ? Number(seed) : undefined,
      description: mode === 'scenario' ? text : undefined,
      testCase: mode === 'testcase' ? { feature, categories: cats, collectionText: spec ? specText : undefined, apiBaseUrl: baseUrl || undefined, selectedEndpoints: picked, businessRules: rules || undefined, useDbSamples: useSamples && !!schema.targetId } : undefined,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, JSON.stringify(tableList), locale, seed, text, feature, cats, specText, spec, baseUrl, picked, rules, useSamples],
  )

  const interpret = useMutation({ mutationFn: () => api.planBlueprint(schema, config), onSuccess: setBp })

  const readSpec = useMutation({
    mutationFn: (t: string) => api.parseCollection(t, schema),
    onSuccess: (p) => {
      setSpec(p)
      setSpecErr(undefined)
      setBaseUrl(p.baseUrl.startsWith('http') ? p.baseUrl : '')
      setPicked(p.endpoints.map((e) => e.id))
    },
    onError: (e) => {
      setSpec(undefined)
      setPicked([])
      setSpecErr((e as Error).message)
    },
  })
  const loadSpec = (t: string) => {
    setSpecText(t)
    setSpec(undefined)
    setSpecErr(undefined)
    if (t.trim()) readSpec.mutate(t)
  }

  const anyTable = tableList.some((t) => t.count > 0)
  const valid = mode === 'fast' ? anyTable : mode === 'scenario' ? anyTable && !!text.trim() : !!spec && picked.length > 0 && cats.length > 0

  const start = () => {
    wf.update({ mode, config, jobId: undefined, downloads: [], loadId: undefined })
    nav('/generate')
  }

  const countsEditor = (
    <Card>
      <CardHeader
        title="Tables and record counts"
        subtitle={mode === 'testcase' ? undefined : 'Select tables and set the number of records for each. Parent tables are added automatically when required.'}
        right={
          <div className="flex gap-2 text-xs font-semibold">
            <button className="text-react" onClick={() => setEnabled(Object.fromEntries(schema.tables.map((t) => [t.name, true])))}>All</button>
            <button className="text-slate-500" onClick={() => setEnabled(Object.fromEntries(schema.tables.map((t) => [t.name, false])))}>None</button>
          </div>
        }
      />
      <div className="divide-y divide-slate-100">
        {schema.tables.map((t) => {
          const blocked = t.needsDefinition && t.columns.length <= 1
          return (
            <div key={t.name} className="flex items-center gap-3 px-5 py-2.5">
              <input type="checkbox" checked={!!enabled[t.name]} onChange={(e) => setEnabled({ ...enabled, [t.name]: e.target.checked })} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{t.name}</div>
                <div className="text-xs text-slate-500">{blocked ? 'Fields not defined, define them in the schema explorer' : `${t.columns.length} fields${t.foreignKeys.length ? `, depends on ${[...new Set(t.foreignKeys.map((f) => f.refTable))].join(', ')}` : ''}`}</div>
              </div>
              <Input type="number" min={0} className="!w-28" disabled={!enabled[t.name]} value={counts[t.name] ?? 0} onChange={(e) => setCounts({ ...counts, [t.name]: Number(e.target.value) })} />
            </div>
          )
        })}
      </div>
    </Card>
  )

  const options = (
    <Card>
      <CardHeader title="Options" />
      <div className="grid gap-4 p-5 sm:grid-cols-2">
        <Field label="Locale">
          <Select value={locale} onChange={(e) => setLocale(e.target.value)}>
            {Object.entries(LOCALES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </Field>
        <Field label="Generation seed (optional)" hint="Use the same seed to repeat a dataset exactly.">
          <Input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="e.g. 42" />
        </Field>
      </div>
    </Card>
  )

  return (
    <div>
      <PageHeader title="Choose a generation mode" subtitle="The journey is identical for every mode. Only the inputs and generated deliverables change." />
      <div className="mb-6 grid gap-4 md:grid-cols-3">
        {MODES.map((m) => (
          <button key={m.id} onClick={() => { setMode(m.id); setBp(undefined) }} className={clsx('rounded-xl border-2 p-5 text-left transition-all', mode === m.id ? `${m.accent} bg-white shadow-md ring-4 ring-react/10` : 'border-slate-200 bg-white hover:border-slate-300')}>
            <div className="flex items-start justify-between">
              <span className={clsx('grid size-10 place-items-center rounded-lg', m.tagLayer === 'AI' ? 'bg-ai-soft text-ai' : 'bg-python-soft text-python')}><m.icon className="size-5" /></span>
              <LayerBadge layer={m.tagLayer} />
            </div>
            <div className="mt-3 flex items-center gap-2 text-base font-semibold">Mode {MODES.indexOf(m) + 1}: {m.title}</div>
            <div className="mt-0.5 text-xs font-medium text-slate-500">{m.tag}</div>
            <ul className="mt-3 space-y-1 text-sm text-slate-600">{m.points.map((p) => <li key={p}>• {p}</li>)}</ul>
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
        <div className="space-y-6">
          {mode === 'scenario' && (
            <Card tone="ai">
              <CardHeader title="Describe the application" subtitle="A basic domain description is enough. Add exact scenarios, statuses and counts for precise workflow states." right={<LayerBadge layer="AI" />} />
              <div className="space-y-4 p-5">
                <Field label="Application description">
                  <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="An Indian university placement management application." />
                </Field>
                <div className="flex flex-wrap gap-2 text-xs">
                  {['An Indian university placement management application', 'Indian grocery delivery app with 20 refunded orders'].map((s) => (
                    <button key={s} className="rounded-full border border-slate-200 px-3 py-1 text-slate-600 hover:bg-slate-50" onClick={() => setDescription(s)}>{s}</button>
                  ))}
                </div>
                <Field label="Advanced: scenarios and counts (optional)" hint="Combined request example: 100 students, 60 placements, 30 approved timesheets, 10 pending timesheets, 5 rejected timesheets.">
                  <Textarea value={advanced} onChange={(e) => setAdvanced(e.target.value)} placeholder="Generate 100 students, 60 placements, 30 approved timesheets, 10 pending timesheets, and 5 rejected timesheets." />
                </Field>
                <div className="flex items-center gap-3">
                  <Button variant="secondary" onClick={() => interpret.mutate()} loading={interpret.isPending} disabled={!text.trim()}>
                    <Sparkles className="size-4" /> Preview interpreted plan
                  </Button>
                  <span className="text-xs text-slate-500">Schema and prompt only are sent to the AI. No credentials.</span>
                </div>
                {bp && (
                  <div className="space-y-3 rounded-lg border border-ai/30 bg-ai-soft/40 p-4 text-sm">
                    <div className="font-semibold text-ai">Interpreted generation plan</div>
                    <div>Locale: <b>{LOCALES[bp.localeHint]?.label}</b></div>
                    {bp.tableCounts.filter((t) => t.count > 0).length > 0 && <div className="flex flex-wrap gap-1.5">{bp.tableCounts.filter((t) => t.count > 0).map((t) => <Badge key={t.table} tone="gray">{t.table}: {t.count}</Badge>)}</div>}
                    {bp.scenarios.length ? (
                      <ul className="space-y-1">{bp.scenarios.map((s, i) => <li key={i}><Badge tone="green">{s.count}</Badge> {s.table}.{s.column} = <b>{s.value}</b></li>)}</ul>
                    ) : <div className="text-slate-600">No explicit scenarios found. Realistic data will be generated for the domain.</div>}
                    {bp.notes.map((n) => <div key={n} className="text-xs text-amber-800">⚠ {n}</div>)}
                    <Button variant="ghost" className="!px-0" onClick={() => {
                      const need = new Map<string, number>()
                      bp.scenarios.forEach((s) => need.set(s.table, (need.get(s.table) ?? 0) + s.count))
                      setCounts((c) => ({ ...c, ...Object.fromEntries([...need].map(([t, n]) => [t, Math.max(n, c[t] ?? 0)])) }))
                      setEnabled((e) => ({ ...e, ...Object.fromEntries([...need.keys()].map((k) => [k, true])) }))
                    }}>Raise counts to cover every scenario</Button>
                  </div>
                )}
              </div>
            </Card>
          )}

          {mode === 'testcase' && (
            <>
              <Card tone="ai">
                <CardHeader title="Your API: Postman collection or OpenAPI" subtitle="Test cases are written against the real requests in this file. The connected database supplies the field rules (required, unique, lengths, enums)." right={<LayerBadge layer="AI" />} />
                <div className="space-y-4 p-5">
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold hover:bg-slate-50">
                      <Upload className="size-4" /> Upload collection (.json) or OpenAPI (.json / .yaml)
                      <input type="file" accept=".json,.yaml,.yml" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; if (f) loadSpec(await f.text()); e.target.value = '' }} />
                    </label>
                    {readSpec.isPending && <span className="text-sm text-slate-500">Reading…</span>}
                    {spec && <Badge tone="green">{spec.kind === 'postman' ? 'Postman' : 'OpenAPI'}: {spec.title}, {spec.endpoints.length} requests, {spec.endpoints.filter((e) => e.table).length} matched to tables</Badge>}
                  </div>
                  <Textarea className="font-mono text-xs" value={specText} onChange={(e) => setSpecText(e.target.value)} onBlur={() => { if (specText.trim() && !spec && !readSpec.isPending) loadSpec(specText) }} placeholder="…or paste the collection / specification here" />
                  {specErr && <Alert tone="error">{specErr}</Alert>}
                  {spec && (
                    <>
                      <Field label="API base URL (optional)" hint="Leave empty to use a {{baseUrl}} variable in the exported Postman collection."><Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://test-api.example.com" /></Field>
                      <div>
                        <div className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-700">
                          <span>Requests to write tests for ({picked.length} of {spec.endpoints.length})</span>
                          <span className="flex gap-3"><button className="text-react" onClick={() => setPicked(spec.endpoints.map((e) => e.id))}>All</button><button className="text-slate-500" onClick={() => setPicked([])}>None</button></span>
                        </div>
                        <div className="max-h-64 divide-y divide-slate-100 overflow-auto rounded-lg border border-slate-200 scroll-thin">
                          {spec.endpoints.map((e) => (
                            <label key={e.id} className="flex items-center gap-3 px-3 py-1.5 text-sm">
                              <input type="checkbox" checked={picked.includes(e.id)} onChange={(ev) => setPicked(ev.target.checked ? [...picked, e.id] : picked.filter((x) => x !== e.id))} />
                              <Badge tone="blue">{e.method}</Badge><span className="font-mono text-xs">{e.path}</span>
                              <span className="truncate text-xs text-slate-500">{e.name}</span>
                              <span className="ml-auto shrink-0 text-xs">{e.table ? <Badge tone="green">{e.table}</Badge> : <span className="text-amber-700">no table matched</span>}</span>
                            </label>
                          ))}
                        </div>
                        {spec.endpoints.some((e) => !e.table && e.hasBody) && <p className="mt-1 text-xs text-amber-800">Requests with no matching table still get tests, but field rules (required, lengths, enums) are unknown, so fewer cases are written.</p>}
                      </div>
                    </>
                  )}
                </div>
              </Card>
              <Card>
                <CardHeader title="What to test" />
                <div className="space-y-4 p-5">
                  <div>
                    <div className="mb-1 text-xs font-semibold text-slate-700">Test categories</div>
                    <div className="flex flex-wrap gap-3">
                      {CATS.map((c) => (
                        <label key={c.id} className="flex items-center gap-2 text-sm">
                          <input type="checkbox" checked={cats.includes(c.id)} onChange={(e) => setCats(e.target.checked ? [...cats, c.id] : cats.filter((x) => x !== c.id))} /> {c.label}
                        </label>
                      ))}
                    </div>
                  </div>
                  <Field label="Focus (optional)" hint="Guides the AI towards what matters, for example refunds or approvals.">
                    <Textarea value={feature} onChange={(e) => setFeature(e.target.value)} placeholder="Student timesheet submission and supervisor approval." />
                  </Field>
                  <Field label="Application rules (optional)" hint="Permissions and duplicate handling cannot be inferred from a schema. Supplying rules makes those cases ready to export.">
                    <Textarea value={rules} onChange={(e) => setRules(e.target.value)} placeholder="Only the placement supervisor may approve. A student may submit one timesheet per placement per week." />
                  </Field>
                  <label className={clsx('flex items-start gap-3 rounded-lg border p-3 text-sm', schema.targetId ? 'border-slate-200' : 'border-slate-100 text-slate-400')}>
                    <input type="checkbox" className="mt-1" disabled={!schema.targetId} checked={useSamples && !!schema.targetId} onChange={(e) => setUseSamples(e.target.checked)} />
                    <span>
                      <b>Use a few existing rows from my database as valid values</b>
                      <span className="block text-xs text-slate-500">Read-only: up to 5 rows from the tables behind the selected requests. Used for real parent ids and for duplicate-value tests. Nothing is written. Leave off if the data is sensitive.</span>
                    </span>
                  </label>
                </div>
              </Card>
            </>
          )}

          {mode !== 'testcase' && countsEditor}
        </div>

        <div className="space-y-6">
          {mode !== 'testcase' && options}
          {mode === 'testcase' && <Card><CardHeader title="How test cases are built" /><div className="space-y-2 p-5 text-sm text-slate-600"><p>Endpoints, methods and example bodies come from your collection. Field rules come from the database schema.</p><p>No test data is generated or loaded, so there is nothing to conflict with existing keys. Negative cases change one field of your own request body.</p></div></Card>}
          <Card tone="react">
            <CardHeader title="Ready to generate" />
            <div className="space-y-3 p-5 text-sm">
              <div className="flex items-center justify-between"><span className="text-slate-500">Mode</span><b>{MODES.find((m) => m.id === mode)!.title}</b></div>
              {mode !== 'testcase' && <div className="flex items-center justify-between"><span className="text-slate-500">Records requested</span><b>{tableList.reduce((s, t) => s + t.count, 0).toLocaleString()}</b></div>}
              <div className="flex items-center justify-between"><span className="text-slate-500">AI required</span><b>{mode === 'fast' ? 'No' : 'Yes'}</b></div>
              <Button className="w-full" disabled={!valid} onClick={start}>Generate</Button>
              {!valid && <p className="text-xs text-slate-500">{mode === 'fast' ? 'Select at least one table with a count above zero.' : mode === 'scenario' ? 'Add an application description and at least one table.' : 'Add your Postman collection or OpenAPI file, pick requests and at least one category.'}</p>}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
