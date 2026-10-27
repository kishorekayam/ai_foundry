import {
  Faker,
  fakerDE,
  fakerEN_GB,
  fakerEN_IN,
  fakerEN_US,
  fakerFR,
} from '@faker-js/faker'
import type { Column, Row, Schema, Table } from '../../types'

export type Dataset = Record<string, Row[]>

export const LOCALES: Record<string, { label: string; faker: Faker }> = {
  en_IN: { label: 'English (India)', faker: fakerEN_IN },
  en_US: { label: 'English (US)', faker: fakerEN_US },
  en_GB: { label: 'English (UK)', faker: fakerEN_GB },
  de: { label: 'German', faker: fakerDE },
  fr: { label: 'French', faker: fakerFR },
}

const PREFIX: Record<string, string> = {
  students: 'STU',
  placements: 'PLC',
  timesheets: 'TS',
  supervisors: 'SUP',
}

const INT_TYPES = ['serial', 'bigserial', 'integer', 'int', 'bigint', 'smallint', 'long']
const NUM_TYPES = ['numeric', 'decimal', 'float', 'double', 'real', 'number']
const DATE_TYPES = ['date', 'timestamp', 'timestamptz', 'datetime']
const TEXT_TYPES = ['varchar', 'text', 'string', 'char']

export const isInt = (t: string) => INT_TYPES.includes(t.toLowerCase())
export const isNum = (t: string) => NUM_TYPES.includes(t.toLowerCase())
export const isDate = (t: string) => DATE_TYPES.includes(t.toLowerCase())
export const isText = (t: string) => TEXT_TYPES.includes(t.toLowerCase())

export function parseRange(check?: string): { min?: number; max?: number } {
  if (!check) return {}
  const out: { min?: number; max?: number } = {}
  const between = check.match(/BETWEEN\s+(-?\d+(?:\.\d+)?)\s+AND\s+(-?\d+(?:\.\d+)?)/i)
  if (between) return { min: Number(between[1]), max: Number(between[2]) }
  const ge = check.match(/>=\s*(-?\d+(?:\.\d+)?)/)
  const gt = check.match(/>\s*(-?\d+(?:\.\d+)?)/)
  const le = check.match(/<=\s*(-?\d+(?:\.\d+)?)/)
  const lt = check.match(/<\s*(-?\d+(?:\.\d+)?)/)
  if (ge) out.min = Number(ge[1])
  else if (gt) out.min = Number(gt[1]) + 1
  if (le) out.max = Number(le[1])
  else if (lt) out.max = Number(lt[1]) - 1
  return out
}

/** Order tables so parents come before children. Self references and cycles are reported, never bypassed. */
export function dependencyOrder(tables: Table[], selected: Set<string>) {
  const names = tables.filter((t) => selected.has(t.name)).map((t) => t.name)
  const indeg = new Map<string, number>(names.map((n) => [n, 0]))
  const edges = new Map<string, string[]>(names.map((n) => [n, []]))
  const selfRefs: string[] = []
  for (const t of tables) {
    if (!selected.has(t.name)) continue
    for (const f of t.foreignKeys) {
      if (f.refTable === t.name) {
        selfRefs.push(t.name)
        continue
      }
      if (!selected.has(f.refTable)) continue
      edges.get(f.refTable)!.push(t.name)
      indeg.set(t.name, (indeg.get(t.name) ?? 0) + 1)
    }
  }
  const queue = names.filter((n) => indeg.get(n) === 0)
  const order: string[] = []
  while (queue.length) {
    const n = queue.shift()!
    order.push(n)
    for (const c of edges.get(n) ?? []) {
      indeg.set(c, indeg.get(c)! - 1)
      if (indeg.get(c) === 0) queue.push(c)
    }
  }
  const cyclic = names.filter((n) => !order.includes(n))
  return { order, cyclic, selfRefs }
}

export function requiredParents(schema: Schema, selected: Set<string>): string[] {
  const added: string[] = []
  const map = new Map(schema.tables.map((t) => [t.name, t]))
  const visit = (name: string) => {
    for (const f of map.get(name)?.foreignKeys ?? []) {
      const col = map.get(name)!.columns.find((c) => c.name === f.column)
      if (f.refTable === name || selected.has(f.refTable) || col?.nullable) continue
      selected.add(f.refTable)
      added.push(f.refTable)
      visit(f.refTable)
    }
  }
  for (const n of [...selected]) visit(n)
  return added
}

const DOMAIN_LISTS: Record<string, Record<string, string[]>> = {
  placement: {
    industry: ['Information Technology', 'Healthcare', 'Manufacturing', 'Finance', 'Education', 'Logistics', 'Retail', 'Energy'],
    department: ['Computer Science', 'Mechanical Engineering', 'Electronics', 'Business Administration', 'Civil Engineering', 'Biotechnology', 'Data Science'],
    role: ['Software Intern', 'Data Analyst Trainee', 'QA Intern', 'Operations Trainee', 'Business Analyst Intern', 'Design Intern'],
  },
  commerce: {
    category: ['Groceries', 'Fresh Produce', 'Dairy', 'Snacks', 'Beverages', 'Household', 'Personal Care'],
    product: ['Basmati Rice 5kg', 'Toor Dal 1kg', 'Amul Butter 500g', 'Masala Tea 250g', 'Atta 10kg', 'Cold Pressed Oil 1L', 'Paneer 200g'],
  },
}

export class GenContext {
  faker: Faker
  dataset: Dataset = {}
  counters: Record<string, number> = {}
  uniques = new Map<string, Set<string>>()
  tableMap: Map<string, Table>
  domainKey?: string

  schema: Schema
  locale: string

  constructor(schema: Schema, locale: string, seed?: number, domain?: string) {
    this.schema = schema
    this.locale = locale
    this.faker = (LOCALES[locale] ?? LOCALES.en_US).faker
    this.faker.seed(seed ?? Math.floor(Math.random() * 1e9))
    this.tableMap = new Map(schema.tables.map((t) => [t.name, t]))
    const d = (domain ?? '').toLowerCase()
    if (/placement|universit|student|college|intern/.test(d) || schema.tables.some((t) => t.name === 'timesheets')) this.domainKey = 'placement'
    if (/grocery|commerce|retail|shop|order/.test(d) || schema.tables.some((t) => t.name === 'order_items')) this.domainKey = 'commerce'
  }

  private pick<T>(arr: T[]): T {
    return this.faker.helpers.arrayElement(arr)
  }

  private domainList(key: string): string[] | undefined {
    return this.domainKey ? DOMAIN_LISTS[this.domainKey]?.[key] : undefined
  }

  private uniq(table: string, col: Column, make: (attempt: number) => string | number) {
    const key = `${table}.${col.name}`
    if (!this.uniques.has(key)) this.uniques.set(key, new Set())
    const set = this.uniques.get(key)!
    for (let a = 0; a < 40; a++) {
      let v = make(a)
      if (typeof v === 'string' && col.maxLength) v = v.slice(0, col.maxLength)
      if (!set.has(String(v))) {
        set.add(String(v))
        return v
      }
    }
    const fallback = typeof make(0) === 'number' ? set.size + 100000 : `${String(make(0)).slice(0, Math.max(1, (col.maxLength ?? 40) - 6))}-${set.size + 1}`
    set.add(String(fallback))
    return fallback
  }

  private recentDate(daysBack: number, daysAhead = 0) {
    return this.faker.date.between({
      from: new Date(Date.now() - daysBack * 864e5),
      to: new Date(Date.now() + daysAhead * 864e5),
    })
  }

  private byName(table: string, c: Column): string | number | boolean | undefined {
    const n = c.name.toLowerCase()
    const f = this.faker
    const t = table.toLowerCase()
    if (n.includes('email')) return f.internet.email().toLowerCase()
    if (n.includes('phone')) return f.phone.number()
    if (n === 'city') return f.location.city()
    if (n === 'country') return this.locale === 'en_US' ? 'United States' : this.locale === 'en_GB' ? 'United Kingdom' : this.locale === 'de' ? 'Germany' : this.locale === 'fr' ? 'France' : 'India'
    if (n === 'industry') return this.pick(this.domainList('industry') ?? ['Technology', 'Finance', 'Healthcare', 'Retail'])
    if (n === 'category') return this.pick(this.domainList('category') ?? ['General', 'Premium', 'Basic'])
    if (n === 'sku') return `SKU-${f.string.alphanumeric({ length: 8, casing: 'upper' })}`
    if (n === 'role_title') return this.pick(this.domainList('role') ?? [f.person.jobTitle()])
    if (n === 'head_name' || n.endsWith('full_name') || (n === 'name' && /user|customer|student|supervisor/.test(t))) return f.person.fullName()
    if (n === 'name') {
      if (t === 'universities') return `${f.location.city()} ${this.pick(['University', 'Institute of Technology', 'College of Engineering'])}`
      if (t === 'departments') return this.pick(this.domainList('department') ?? [f.commerce.department()])
      if (t === 'products') return this.pick(this.domainList('product') ?? [f.commerce.productName()])
      if (/provider|compan/.test(t)) return f.company.name()
      return f.commerce.productName()
    }
    if (n === 'subject') return f.lorem.sentence({ min: 3, max: 8 }).replace(/\.$/, '')
    if (n === 'notes' || n === 'comment' || n === 'description') return f.lorem.sentence()
    if (n === 'method') return undefined
    return undefined
  }

  private numeric(c: Column, int: boolean): number {
    const r = parseRange(c.check)
    const n = c.name.toLowerCase()
    let min = r.min ?? 0
    let max = r.max ?? 1000
    if (r.min === undefined && r.max === undefined) {
      if (n.includes('year')) {
        min = 2015
        max = 2025
      } else if (n.includes('hours')) {
        min = 10
        max = 45
      } else if (n.includes('price') || n.includes('amount')) {
        min = 49
        max = 4999
      } else if (n.includes('stock') || n.includes('quantity')) {
        min = 1
        max = 50
      }
    }
    if (r.min !== undefined && r.max === undefined) max = r.min + 1000
    if (r.max !== undefined && r.min === undefined) min = Math.min(0, r.max)
    return int ? this.faker.number.int({ min: Math.ceil(min), max: Math.floor(max) }) : Number(this.faker.number.float({ min, max, fractionDigits: 2 }).toFixed(2))
  }

  nextKey(table: string, c: Column): string | number {
    const idx = (this.counters[table] = (this.counters[table] ?? 0) + 1) - 1
    const t = c.type.toLowerCase()
    if (t === 'objectid') return this.faker.string.hexadecimal({ length: 24, casing: 'lower', prefix: '' })
    if (t === 'uuid') return this.faker.string.uuid()
    if (isInt(t)) return idx + 1
    const prefix = PREFIX[table] ?? table.replace(/[^a-z]/gi, '').slice(0, 3).toUpperCase()
    return `${prefix}${101 + idx}`
  }

  private fromColumn(table: Table, c: Column): Row[string] {
    if (c.enumValues?.length) return this.pick(c.enumValues)
    const t = c.type.toLowerCase()
    const hint = this.byName(table.name, c)
    if (hint !== undefined) return c.unique ? this.uniq(table.name, c, (a) => (a ? `${hint}${a}` : String(hint))) : hint
    if (t === 'boolean' || t === 'bool') return this.faker.datatype.boolean({ probability: c.default === 'true' ? 0.9 : 0.5 })
    if (isInt(t)) return this.numeric(c, true)
    if (isNum(t)) return this.numeric(c, false)
    if (t === 'date') return this.recentDate(300).toISOString().slice(0, 10)
    if (isDate(t)) return this.recentDate(300).toISOString()
    const max = c.maxLength ?? 60
    const text = this.faker.lorem.words({ min: 1, max: 3 }).slice(0, max)
    return c.unique ? this.uniq(table.name, c, (a) => `${text}${a || ''}`) : text
  }

  /** Create one row, resolving foreign keys against already generated parents. */
  addRow(tableName: string, forced: Row = {}, parents: Record<string, Row> = {}): Row {
    const table = this.tableMap.get(tableName)!
    const rows = (this.dataset[tableName] ??= [])
    const row: Row = {}
    const fkCols = new Map(table.foreignKeys.map((f) => [f.column, f]))

    // Explicit parent rows (used for isolated per-test prerequisites)
    const done = new Set<string>()
    for (const f of table.foreignKeys) {
      const p = parents[f.refTable]
      if (p && !(f.column in forced) && f.refTable !== tableName) {
        row[f.column] = p[f.refColumn]
        done.add(f.column)
      }
    }

    // Anchor FKs first: if parent P references table Q and this table also references Q directly,
    // derive that column from the chosen P row so the record stays coherent.
    for (const f of table.foreignKeys) {
      if (done.has(f.column) || f.column in forced || f.refTable === tableName) continue
      const parentTable = this.tableMap.get(f.refTable)
      const parentRows = this.dataset[f.refTable] ?? []
      if (!parentTable || !parentRows.length) continue
      const siblings = parentTable.foreignKeys.filter((pf) => table.foreignKeys.some((g) => g !== f && g.refTable === pf.refTable))
      if (!siblings.length) continue
      const parent = this.pick(parentRows)
      row[f.column] = parent[f.refColumn]
      done.add(f.column)
      for (const pf of siblings) {
        const g = table.foreignKeys.find((x) => x !== f && x.refTable === pf.refTable)!
        if (!(g.column in forced) && !done.has(g.column)) {
          row[g.column] = parent[pf.column]
          done.add(g.column)
        }
      }
    }

    for (const c of table.columns) {
      if (c.name in forced) {
        row[c.name] = forced[c.name]
        continue
      }
      if (done.has(c.name)) continue
      if (c.primaryKey) {
        row[c.name] = this.nextKey(tableName, c)
        continue
      }
      const f = fkCols.get(c.name)
      if (f) {
        const pool = f.refTable === tableName ? rows : (this.dataset[f.refTable] ?? [])
        row[c.name] = pool.length ? (this.pick(pool)[f.refColumn] as Row[string]) : null
        continue
      }
      if (c.nullable && this.faker.number.float() < 0.15) {
        row[c.name] = null
        continue
      }
      const v = this.fromColumn(table, c)
      row[c.name] = typeof v === 'string' && c.maxLength ? v.slice(0, c.maxLength) : v
    }

    // Keep date pairs ordered (start/end, week/submitted)
    const dateCols = table.columns.filter((c) => isDate(c.type))
    const start = dateCols.find((c) => /^start|week_start/.test(c.name))
    const end = dateCols.find((c) => /^end/.test(c.name))
    if (start && end && row[start.name] && row[end.name] && !(end.name in forced)) {
      row[end.name] = new Date(new Date(String(row[start.name])).getTime() + this.faker.number.int({ min: 60, max: 180 }) * 864e5).toISOString().slice(0, 10)
    }
    const sub = dateCols.find((c) => /submitted_at/.test(c.name))
    if (start && sub && !(sub.name in forced) && row[start.name]) {
      row[sub.name] = new Date(new Date(String(row[start.name])).getTime() + this.faker.number.int({ min: 5, max: 7 }) * 864e5).toISOString()
    }
    const rev = dateCols.find((c) => /reviewed_at/.test(c.name))
    if (rev && !(rev.name in forced) && row.timesheet_id) {
      const ts = (this.dataset.timesheets ?? []).find((r) => r.timesheet_id === row.timesheet_id)
      if (ts?.submitted_at) row[rev.name] = new Date(new Date(String(ts.submitted_at)).getTime() + this.faker.number.int({ min: 1, max: 4 }) * 864e5).toISOString()
    }
    rows.push(row)
    return row
  }

  /** Build a row without keeping it (used for API request fixtures). */
  sampleRow(tableName: string, forced: Row = {}): Row {
    const rows = (this.dataset[tableName] ??= [])
    const before = this.counters[tableName] ?? 0
    const row = this.addRow(tableName, forced)
    rows.pop()
    this.counters[tableName] = before
    return row
  }

  pkOf(tableName: string, row: Row): string {
    const pk = this.tableMap.get(tableName)!.columns.find((c) => c.primaryKey)
    return String(row[pk?.name ?? ''])
  }

  /** Create a row plus fresh parents `depth` levels up; deeper ancestors reuse existing rows. */
  createChain(tableName: string, forced: Row, depth: number, created: { table: string; key: string }[]): Row {
    const table = this.tableMap.get(tableName)!
    const fks = table.foreignKeys.filter((f) => f.refTable !== tableName)
    const parents: Record<string, Row> = {}
    const anchors = fks.filter((f) => this.tableMap.get(f.refTable)!.foreignKeys.some((pf) => fks.some((g) => g !== f && g.refTable === pf.refTable)))
    for (const f of [...anchors, ...fks.filter((x) => !anchors.includes(x))]) {
      if (parents[f.refTable] || f.column in forced) continue
      const pool = this.dataset[f.refTable] ?? []
      const parent = depth > 0 || !pool.length ? this.createChain(f.refTable, {}, Math.max(depth - 1, 0), created) : this.faker.helpers.arrayElement(pool)
      parents[f.refTable] = parent
      for (const pf of this.tableMap.get(f.refTable)!.foreignKeys) {
        const sib = fks.find((g) => g !== f && g.refTable === pf.refTable)
        if (sib && !parents[sib.refTable]) {
          const match = (this.dataset[sib.refTable] ?? []).find((r) => r[sib.refColumn] === parent[pf.column])
          if (match) parents[sib.refTable] = match
        }
      }
    }
    const row = this.addRow(tableName, forced, parents)
    created.push({ table: tableName, key: this.pkOf(tableName, row) })
    return row
  }
}
