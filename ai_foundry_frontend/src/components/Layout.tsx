// src/components/Layout.tsx
import clsx from 'clsx'
import { Check, ShieldCheck } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { AUTH_EVENT, clearCredentials } from '../api/auth'
import { useWorkflow } from '../store/workflow'
import { Badge } from './ui'

export const STEPS = [
  { path: '/connect', label: 'Connect', n: '1-2' },
  { path: '/schema', label: 'Schema', n: '3' },
  { path: '/mode', label: 'Mode', n: '4' },
  { path: '/generate', label: 'Generate', n: '5' },
  { path: '/preview', label: 'Preview & validate', n: '6' },
  { path: '/output', label: 'Output', n: '7' },
  { path: '/result', label: 'Result', n: '8' },
]

export function Logo({ size = 40 }: { size?: number }) {
  return <img src="/logo.png" alt="ESI logo" width={size} height={size} className="shrink-0 object-contain" />
}

export default function Layout() {
  const wf = useWorkflow()
  const { pathname } = useLocation()
  const nav = useNavigate()
  const current = STEPS.findIndex((s) => pathname.startsWith(s.path))
  const reached = [true, !!wf.schema, !!wf.schema, !!wf.config, !!wf.jobId, !!wf.jobId, !!wf.jobId]

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3">
          <Link to="/connect" className="flex items-center gap-3">
            <Logo />
            <div>
              <div className="text-sm font-bold leading-tight tracking-wide text-ink">ATOM DATA FOUNDRY</div>
              <div className="text-[11px] leading-tight text-slate-500">AI-powered synthetic test data & test case generation</div>
            </div>
          </Link>
          <div className="flex items-center gap-3">
            <Badge tone={api.mode === 'mock' ? 'amber' : 'green'}>{api.mode === 'mock' ? 'Demo engine (in-browser)' : 'Connected to FastAPI'}</Badge>
            <NavLink to="/how-it-works" className={({ isActive }) => clsx('text-sm font-medium', isActive ? 'text-react' : 'text-slate-600 hover:text-ink')}>
              How it works
            </NavLink>
            {api.mode === 'http' && (
              <button
                onClick={() => {
                  clearCredentials()
                  wf.reset()
                  window.dispatchEvent(new Event(AUTH_EVENT))
                }}
                className="text-sm font-medium text-slate-600 hover:text-ink"
              >
                Sign out
              </button>
            )}
            {wf.schema && (
              <button
                onClick={() => {
                  wf.reset()
                  nav('/connect')
                }}
                className="text-sm font-medium text-slate-600 hover:text-ink"
              >
                New session
              </button>
            )}
          </div>
        </div>
        {current >= 0 && (
          <nav className="mx-auto max-w-7xl overflow-x-auto px-6 pb-3 scroll-thin">
            <ol className="flex min-w-max items-center gap-2">
              {STEPS.map((s, i) => {
                const done = i < current
                const ok = reached[i]
                return (
                  <li key={s.path} className="flex items-center gap-2">
                    <button
                      disabled={!ok || i === current}
                      onClick={() => nav(s.path)}
                      className={clsx(
                        'flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors',
                        i === current && 'border-react bg-react text-white',
                        i !== current && done && 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100',
                        i > current && 'border-slate-200 bg-white text-slate-500',
                        !ok && 'cursor-not-allowed opacity-60',
                      )}
                    >
                      <span className={clsx('grid size-5 place-items-center rounded-full text-[10px]', i === current ? 'bg-white/20' : done ? 'bg-emerald-600 text-white' : 'bg-slate-100')}>{done ? <Check className="size-3" /> : s.n}</span>
                      {s.label}
                    </button>
                    {i < STEPS.length - 1 && <span className="h-px w-4 bg-slate-300" />}
                  </li>
                )
              })}
            </ol>
          </nav>
        )}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-1 px-6 py-3 text-xs text-slate-500">
          <span className="flex items-center gap-1.5 font-medium text-slate-700">
            <ShieldCheck className="size-4 text-emerald-600" /> Built-in controls
          </span>
          <span>Only approved databases can be connected</span>
          <span>Credentials never reach the AI service or logs</span>
          <span>Nothing loads without your approval</span>
        </div>
      </footer>
    </div>
  )
}
