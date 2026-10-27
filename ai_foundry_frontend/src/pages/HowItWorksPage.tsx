import { ArrowRight } from 'lucide-react'
import { Card, CardHeader, LayerBadge, PageHeader } from '../components/ui'

const FLOW = [
  ['Connect database', 'React', 'PostgreSQL, MySQL or MongoDB. Test Connection against approved targets.'],
  ['Extract schema metadata', 'Boomi', 'Metadata process via JDBC queries or the Python adapter.'],
  ['Display schema', 'React', 'Tables, fields, types and an interactive relationship graph.'],
  ['Select a mode', 'React', 'Fast Test, AI Realistic & Scenario, or AI Test Case Generator.'],
  ['Generate', 'AI', 'AI plans the rules, Python creates synthetic data, or writes test cases against your Postman collection.'],
  ['Preview & validate', 'React', '20 rows per table, quality reports and missing coverage.'],
  ['Choose output', 'React', 'Excel, CSV ZIP, JSON, SQL, Postman, or an approved database load.'],
  ['Final result', 'React', 'Downloads or load status and the readiness report.'],
] as const

const OWNERS: [string, string][] = [
  ['React', 'Entire user interface, visualizations, previews and downloads'],
  ['Boomi', 'Metadata integration, routing, loading orchestration and execution reporting'],
  ['Python', 'Synthetic record generation, relationships, validations, exports and loading'],
  ['AI', 'Domain reasoning, scenario plans and business-rule test cases'],
  ['Database', 'Schema source and optional synthetic-data destination'],
]

export default function HowItWorksPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="How ATOM DATA FOUNDRY works" subtitle="React owns the interface, FastAPI owns the logic, Boomi orchestrates integration, AI reasons about the domain." />
      <Card>
        <CardHeader title="One journey for every mode" subtitle="Only the inputs and the generated deliverables change." />
        <ol className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-4">
          {FLOW.map(([t, layer, d], i) => (
            <li key={t} className="rounded-xl border border-slate-200 p-4">
              <div className="flex items-center justify-between"><span className="grid size-7 place-items-center rounded-full bg-react text-xs font-bold text-white">{i + 1}</span><LayerBadge layer={layer} /></div>
              <div className="mt-2 text-sm font-semibold">{t}</div>
              <p className="mt-1 text-xs text-slate-500">{d}</p>
            </li>
          ))}
        </ol>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Technology ownership" />
          <dl className="divide-y divide-slate-100">
            {OWNERS.map(([k, v]) => <div key={k} className="flex items-start gap-3 px-5 py-3 text-sm"><dt className="w-24 shrink-0"><LayerBadge layer={k} /></dt><dd className="text-slate-600">{v}</dd></div>)}
          </dl>
        </Card>
        <Card>
          <CardHeader title="Generation pipeline" subtitle="One Python engine serves all three modes. Parents are always generated before children." />
          <div className="flex flex-wrap items-center gap-2 p-5 text-xs font-medium">
            {['Validated schema', 'Mode rules', 'Dependency graph', 'Parent records', 'Child records', 'Scenario rules', 'Validate all', 'Store dataset'].map((s, i, a) => (
              <span key={s} className="flex items-center gap-2"><span className="rounded-lg border border-python/30 bg-python-soft px-2.5 py-1.5">{s}</span>{i < a.length - 1 && <ArrowRight className="size-3.5 text-slate-400" />}</span>
            ))}
          </div>
          <div className="border-t border-slate-100 p-5 text-xs text-slate-600">
            Nine checks run before any insert is offered: data type, required fields, string length, primary key, foreign key, unique constraint, enum and check constraints, scenario counts, test-case linkage.
          </div>
        </Card>
      </div>
      <Card>
        <CardHeader title="Backend connection" />
        <div className="space-y-2 p-5 text-sm text-slate-600">
          <p>By default the app runs an in-browser demo engine that really generates and validates data from the schema, so every screen works without a server.</p>
          <p>Set <code className="rounded bg-slate-100 px-1.5 py-0.5">VITE_API_BASE</code> to your FastAPI origin to switch to the real backend. The REST contract is in <code className="rounded bg-slate-100 px-1.5 py-0.5">src/api/httpApi.ts</code>.</p>
        </div>
      </Card>
    </div>
  )
}
