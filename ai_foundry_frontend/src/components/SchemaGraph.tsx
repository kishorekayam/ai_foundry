import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import clsx from 'clsx'
import { KeyRound, Link2 } from 'lucide-react'
import { useMemo } from 'react'
import type { Schema, Table } from '../types'

type TNode = Node<{ table: Table; selected: boolean; highlight?: string }, 'table'>

function TableNode({ data }: NodeProps<TNode>) {
  const { table, selected } = data
  const fkCols = new Set(table.foreignKeys.map((f) => f.column))
  const shown = table.columns.slice(0, 5)
  return (
    <div className={clsx('w-52 overflow-hidden rounded-lg border-2 bg-white shadow-sm', selected ? 'border-react shadow-md' : 'border-slate-300')}>
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />
      <div className={clsx('flex items-center justify-between px-3 py-1.5 text-xs font-bold', selected ? 'bg-react text-white' : 'bg-python-soft text-python')}>
        <span className="truncate">{table.name}</span>
        <span className="font-medium opacity-70">{table.columns.length}</span>
      </div>
      <ul className="divide-y divide-slate-100 text-[11px]">
        {shown.map((c) => (
          <li key={c.name} className="flex items-center gap-1.5 px-3 py-1">
            {c.primaryKey ? <KeyRound className="size-3 text-amber-600" /> : fkCols.has(c.name) ? <Link2 className="size-3 text-react" /> : <span className="size-3" />}
            <span className="truncate font-medium">{c.name}</span>
            <span className="ml-auto text-slate-400">{c.type}</span>
          </li>
        ))}
        {table.columns.length > shown.length && <li className="px-3 py-1 text-slate-400">+{table.columns.length - shown.length} more</li>}
        {table.needsDefinition && <li className="bg-amber-50 px-3 py-1 font-medium text-amber-700">fields missing</li>}
      </ul>
      <Handle type="source" position={Position.Right} className="!bg-slate-400" />
    </div>
  )
}

const nodeTypes = { table: TableNode }

function layout(tables: Table[]) {
  const level = new Map<string, number>()
  const visit = (t: Table, stack: string[]): number => {
    if (level.has(t.name)) return level.get(t.name)!
    if (stack.includes(t.name)) return 0
    const parents = t.foreignKeys.filter((f) => f.refTable !== t.name).map((f) => tables.find((x) => x.name === f.refTable)).filter(Boolean) as Table[]
    const l = parents.length ? Math.max(...parents.map((p) => visit(p, [...stack, t.name]))) + 1 : 0
    level.set(t.name, l)
    return l
  }
  tables.forEach((t) => visit(t, []))
  const rows = new Map<number, number>()
  return new Map(
    tables.map((t) => {
      const l = level.get(t.name)!
      const r = rows.get(l) ?? 0
      rows.set(l, r + 1)
      return [t.name, { x: l * 320, y: r * 190 }]
    }),
  )
}

export default function SchemaGraph({ schema, selected, onSelect }: { schema: Schema; selected?: string; onSelect: (t: string) => void }) {
  const { nodes, edges } = useMemo(() => {
    const pos = layout(schema.tables)
    const nodes: TNode[] = schema.tables.map((t) => ({ id: t.name, type: 'table', position: pos.get(t.name)!, data: { table: t, selected: t.name === selected }, draggable: true }))
    const edges: Edge[] = schema.tables.flatMap((t) =>
      t.foreignKeys.filter((f) => f.refTable !== t.name).map((f) => ({
        id: `${f.refTable}-${t.name}-${f.column}`,
        source: f.refTable,
        target: t.name,
        label: f.column,
        labelStyle: { fontSize: 10, fill: '#475569' },
        labelBgStyle: { fill: '#f5f7fb' },
        style: { stroke: selected && (selected === t.name || selected === f.refTable) ? '#0f52ba' : '#94a3b8', strokeWidth: selected && (selected === t.name || selected === f.refTable) ? 2 : 1.2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' },
        animated: selected === t.name || selected === f.refTable,
      })),
    )
    return { nodes, edges }
  }, [schema, selected])

  return (
    <div className="h-[560px] overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={(_, n) => onSelect(n.id)} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.3}>
        <Background gap={20} color="#dbe0ea" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
