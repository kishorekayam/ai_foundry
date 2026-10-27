import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Link2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Job, Schema } from '../types'
import { Badge, Card, CardHeader } from './ui'

const PAGE = 20

export default function DataPreview({ job, schema, initialTable }: { job: Job; schema: Schema; initialTable?: string }) {
  const tables = job.report!.perTable.filter((t) => t.generated > 0)
  const [table, setTable] = useState(initialTable ?? tables[0]?.table)
  const [page, setPage] = useState(0)
  useEffect(() => {
    if (initialTable) setTable(initialTable)
  }, [initialTable])
  useEffect(() => setPage(0), [table])

  const data = useQuery({
    queryKey: ['preview', job.id, table, page, job.report!.recordsGenerated],
    queryFn: () => api.getPreview(job.id, table, page, PAGE),
    enabled: !!table,
    placeholderData: (p) => p,
  })
  const meta = schema.tables.find((t) => t.name === table)
  const pages = data.data ? Math.max(1, Math.ceil(data.data.total / PAGE)) : 1
  const fk = new Map(meta?.foreignKeys.map((f) => [f.column, f]))
  const failing = job.report!.checks.filter((c) => c.status === 'failed' || c.status === 'warning')

  return (
    <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
      <Card className="h-fit">
        <CardHeader title="Tables" />
        <ul className="divide-y divide-slate-100">
          {tables.map((t) => (
            <li key={t.table}>
              <button onClick={() => setTable(t.table)} className={clsx('flex w-full items-center justify-between px-4 py-2.5 text-left text-sm', table === t.table ? 'bg-react-soft font-semibold text-react' : 'hover:bg-slate-50')}>
                <span className="truncate">{t.table}</span>
                <span className="text-xs text-slate-500">{t.generated.toLocaleString()}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader
          title={`${table} preview`}
          subtitle={data.data ? `${Math.min(PAGE, data.data.total)} of ${data.data.total.toLocaleString()} records, retrieved page by page` : undefined}
          right={
            <div className="flex items-center gap-2 text-xs">
              <button disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded border border-slate-300 p-1 disabled:opacity-40"><ChevronLeft className="size-4" /></button>
              <span>Page {page + 1} of {pages}</span>
              <button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)} className="rounded border border-slate-300 p-1 disabled:opacity-40"><ChevronRight className="size-4" /></button>
            </div>
          }
        />
        {meta && meta.foreignKeys.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-2 text-xs text-slate-600">
            <Link2 className="size-3.5" /> Relationships:
            {meta.foreignKeys.map((f) => <Badge key={f.column} tone="blue">{f.column} → {f.refTable}.{f.refColumn}</Badge>)}
          </div>
        )}
        {failing.length > 0 && (
          <div className="flex flex-wrap gap-2 border-b border-slate-100 px-5 py-2 text-xs">
            {failing.map((c) => <Badge key={c.id} tone={c.status === 'failed' ? 'red' : 'amber'}>{c.label}: {c.detail}</Badge>)}
          </div>
        )}
        <div className="overflow-auto scroll-thin">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-50 text-slate-500">
              <tr>
                {data.data?.links && <th className="px-3 py-2">Test IDs</th>}
                {data.data?.columns.map((c) => <th key={c} className="whitespace-nowrap px-3 py-2 font-semibold">{c}{fk.has(c) && <Link2 className="ml-1 inline size-3 text-react" />}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.data?.rows.map((r, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  {data.data!.links && <td className="px-3 py-1.5">{data.data!.links[i]?.map((id) => <Badge key={id} tone="green">{id}</Badge>)}</td>}
                  {data.data!.columns.map((c) => (
                    <td key={c} className="max-w-56 truncate whitespace-nowrap px-3 py-1.5" title={String(r[c] ?? '')}>
                      {r[c] === null ? <span className="text-slate-300">null</span> : String(r[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
