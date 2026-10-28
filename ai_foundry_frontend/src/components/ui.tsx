// src/components/ui.tsx
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Circle, Info, Loader2, XCircle } from 'lucide-react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import type { StepState } from '../types'

export type Layer = 'React' | 'Boomi' | 'Python' | 'FastAPI' | 'AI' | 'Database'

export const layerStyle: Record<string, string> = {
  React: 'bg-react-soft text-react border-react/30',
  Boomi: 'bg-boomi-soft text-boomi border-boomi/30',
  Python: 'bg-python-soft text-python border-python/30',
  FastAPI: 'bg-python-soft text-python border-python/30',
  AI: 'bg-ai-soft text-ai border-ai/40',
  Database: 'bg-db-soft text-db border-db/30',
}

export function LayerBadge({ layer }: { layer: string }) {
  return <span className={clsx('inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold', layerStyle[layer] ?? layerStyle.Database)}>{layer}</span>
}

export function Badge({ children, tone = 'gray' }: { children: ReactNode; tone?: 'gray' | 'green' | 'amber' | 'red' | 'blue' }) {
  const tones = {
    gray: 'bg-slate-100 text-slate-700',
    green: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    red: 'bg-red-50 text-red-700',
    blue: 'bg-react-soft text-react',
  }
  return <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', tones[tone])}>{children}</span>
}

export function Card({ className, children, tone }: { className?: string; children: ReactNode; tone?: 'react' | 'boomi' | 'ai' | 'python' }) {
  const t = tone && { react: 'border-react/30', boomi: 'border-boomi/30', ai: 'border-ai/40', python: 'border-python/30' }[tone]
  return <div className={clsx('rounded-xl border bg-white shadow-sm', t ?? 'border-slate-200', className)}>{children}</div>
}

export function CardHeader({ title, subtitle, right }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  )
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; loading?: boolean }
export function Button({ variant = 'primary', loading, className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: 'bg-react text-white hover:bg-[#0c44a0] disabled:bg-slate-300',
    secondary: 'bg-white text-ink border border-slate-300 hover:bg-slate-50 disabled:text-slate-400',
    ghost: 'text-react hover:bg-react-soft disabled:text-slate-400',
    danger: 'bg-boomi text-white hover:bg-[#ad2750] disabled:bg-slate-300',
  }[variant]
  return (
    <button {...p} disabled={disabled || loading} className={clsx('inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed', v, className)}>
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  )
}

const inputCls = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-ink placeholder:text-slate-400 focus:border-react focus:outline-none focus:ring-2 focus:ring-react/20 disabled:bg-slate-50'

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={clsx('block', className)}>
      <span className="mb-1 block text-xs font-semibold text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={clsx(inputCls, p.className)} />
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={clsx(inputCls, 'min-h-24 resize-y', p.className)} />
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={clsx(inputCls, p.className)} />

export function Alert({ tone = 'info', title, children }: { tone?: 'info' | 'success' | 'warning' | 'error'; title?: string; children?: ReactNode }) {
  const m = {
    info: ['bg-react-soft border-react/30 text-[#0b3f91]', Info],
    success: ['bg-emerald-50 border-emerald-200 text-emerald-800', CheckCircle2],
    warning: ['bg-amber-50 border-amber-200 text-amber-900', AlertTriangle],
    error: ['bg-red-50 border-red-200 text-red-800', XCircle],
  } as const
  const [cls, Icon] = m[tone]
  return (
    <div className={clsx('flex gap-3 rounded-lg border px-4 py-3 text-sm', cls)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div>
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
    </div>
  )
}

export function StepIcon({ state }: { state: StepState }) {
  if (state === 'done') return <CheckCircle2 className="size-5 text-emerald-600" />
  if (state === 'running') return <Loader2 className="size-5 animate-spin text-react" />
  if (state === 'failed') return <XCircle className="size-5 text-red-600" />
  return <Circle className="size-5 text-slate-300" />
}

export function Timeline({ steps }: { steps: { id: string; layer: string; label: string; state: StepState; detail?: string }[] }) {
  return (
    <ol className="space-y-1">
      {steps.map((s) => (
        <li key={s.id} className={clsx('flex items-start gap-3 rounded-lg px-3 py-2', s.state === 'running' && 'bg-react-soft/60')}>
          <StepIcon state={s.state} />
          <div className="min-w-0 flex-1">
            <div className={clsx('text-sm', s.state === 'pending' ? 'text-slate-400' : 'font-medium text-ink')}>{s.label}</div>
            {s.detail && <div className="text-xs text-slate-500">{s.detail}</div>}
          </div>
          <LayerBadge layer={s.layer} />
        </li>
      ))}
    </ol>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'green' | 'amber' | 'red' }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={clsx('mt-1 text-2xl font-semibold', tone === 'green' && 'text-emerald-700', tone === 'amber' && 'text-amber-700', tone === 'red' && 'text-red-700')}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="flex gap-1 border-b border-slate-200">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)} className={clsx('-mb-px border-b-2 px-4 py-2 text-sm font-semibold transition-colors', value === t.id ? 'border-react text-react' : 'border-transparent text-slate-500 hover:text-ink')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Progress({ value, tone = 'blue' }: { value: number; tone?: 'blue' | 'green' }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-100">
      <div className={clsx('h-full rounded-full transition-all', tone === 'green' ? 'bg-emerald-500' : 'bg-react')} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  )
}
