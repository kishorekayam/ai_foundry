import { KeyRound, Link2, Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SchemaGraph from '../components/SchemaGraph'
import { Alert, Badge, Button, Card, CardHeader, Input, LayerBadge, PageHeader, Select, Stat } from '../components/ui'
import { useWorkflow } from '../store/workflow'
import type { Column, Table } from '../types'

function TableDetail({ table, onAddField }: { table: Table; onAddField: (c: Column) => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('string')
  const [nullable, setNullable] = useState(true)
  const fk = new Map(table.foreignKeys.map((f) => [f.column, f]))
  return (
    <Card>
      <CardHeader title={table.name} subtitle={`${table.columns.length} fields, ${table.foreignKeys.length} relationship(s)`} />
      <div className="max-h-[420px] overflow-auto scroll-thin">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2">Field</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Constraints</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {table.columns.map((c) => (
              <tr key={c.name}>
                <td className="px-3 py-2 font-medium">
                  <span className="flex items-center gap-1.5">
                    {c.primaryKey ? <KeyRound className="size-3.5 text-amber-600" /> : fk.has(c.name) ? <Link2 className="size-3.5 text-react" /> : null}
                    {c.name}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-600">
                  {c.type}
                  {c.maxLength ? `(${c.maxLength})` : ''}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {c.primaryKey && <Badge tone="amber">PK</Badge>}
                    {fk.has(c.name) && <Badge tone="blue">FK → {fk.get(c.name)!.refTable}.{fk.get(c.name)!.refColumn}</Badge>}
                    {c.unique && !c.primaryKey && <Badge>unique</Badge>}
                    {!c.nullable && !c.primaryKey && <Badge>required</Badge>}
                    {c.default && <Badge>default {c.default}</Badge>}
                    {c.enumValues && <Badge tone="green">enum: {c.enumValues.join(' | ')}</Badge>}
                    {c.check && <Badge tone="amber">check: {c.check}</Badge>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.needsDefinition && (
        <div className="space-y-3 border-t border-slate-100 p-4">
          <Alert tone="warning" title="Fields not discovered">No schema validator exists for this collection. Define its fields manually; they are marked as user-defined, not discovered.</Alert>
          <div className="flex gap-2">
            <Input placeholder="field name" value={name} onChange={(e) => setName(e.target.value)} />
            <Select value={type} onChange={(e) => setType(e.target.value)} className="!w-32">
              {['string', 'int', 'double', 'boolean', 'date'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </Select>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!nullable} onChange={(e) => setNullable(!e.target.checked)} /> required</label>
            <Button variant="secondary" disabled={!name.trim()} onClick={() => { onAddField({ name: name.trim(), type, nullable, primaryKey: false, unique: false }); setName('') }}><Plus className="size-4" /></Button>
          </div>
        </div>
      )}
    </Card>
  )
}

export default function SchemaPage() {
  const wf = useWorkflow()
  const nav = useNavigate()
  const schema = wf.schema!
  const [selected, setSelected] = useState<string>(schema.tables[0]?.name)
  const table = schema.tables.find((t) => t.name === selected)
  const rels = schema.tables.reduce((s, t) => s + t.foreignKeys.length, 0)
  const cols = schema.tables.reduce((s, t) => s + t.columns.length, 0)
  const incomplete = schema.tables.filter((t) => t.needsDefinition && t.columns.length <= 1)

  const addField = (c: Column) =>
    wf.update({ schema: { ...schema, tables: schema.tables.map((t) => (t.name === selected ? { ...t, columns: [...t.columns, c] } : t)), warnings: schema.warnings } })

  return (
    <div>
      <PageHeader
        title="Schema explorer"
        subtitle={`${schema.database} (${schema.dbType}). Click a table to see its fields, keys and relationships.`}
        actions={<Button onClick={() => nav('/mode')}>Choose generation mode</Button>}
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Stat label="Tables / collections" value={schema.tables.length} />
        <Stat label="Fields" value={cols} />
        <Stat label="Relationships" value={rels} sub={schema.dbType === 'mongodb' ? 'not discoverable' : undefined} />
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
          <div className="text-xs font-medium text-slate-500">Metadata source</div>
          <div className="mt-2 flex items-center gap-2"><LayerBadge layer="Boomi" /><span className="text-sm font-medium">{schema.source === 'boomi-jdbc' ? 'JDBC queries' : 'PyMongo adapter'}</span></div>
        </div>
      </div>
      {schema.warnings.length > 0 && (
        <div className="mb-6 space-y-2">
          {schema.warnings.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
        </div>
      )}
      {incomplete.length > 0 && <div className="mb-6"><Alert tone="info" title="Missing information is shown as missing">{incomplete.map((t) => t.name).join(', ')} need field definitions before data can be generated for them.</Alert></div>}
      <div className="grid gap-6 lg:grid-cols-[1fr_440px]">
        <SchemaGraph schema={schema} selected={selected} onSelect={setSelected} />
        {table && <TableDetail table={table} onAddField={addField} />}
      </div>
    </div>
  )
}
