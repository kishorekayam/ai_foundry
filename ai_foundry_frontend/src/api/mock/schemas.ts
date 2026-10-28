// src/api/mock/schemas.ts
import type { ApprovedTarget, Column, ForeignKey, Schema, Table } from '../../types'

export const APPROVED_TARGETS: ApprovedTarget[] = [
  {
    id: 'pg-placement-test',
    label: 'Placement test DB (PostgreSQL)',
    dbType: 'postgresql',
    host: 'placement-test.atom.internal',
    port: 5432,
    database: 'placement_test_db',
    loadAllowed: true,
  },
  {
    id: 'mysql-retail-test',
    label: 'Retail test DB (MySQL)',
    dbType: 'mysql',
    host: 'retail-test.atom.internal',
    port: 3306,
    database: 'retail_test_db',
    loadAllowed: false,
  },
  {
    id: 'mongo-support-test',
    label: 'Support test DB (MongoDB)',
    dbType: 'mongodb',
    host: 'support-test.atom.internal',
    port: 27017,
    database: 'support_test_db',
    loadAllowed: false,
  },
]

const col = (name: string, type: string, o: Partial<Column> = {}): Column => ({
  name,
  type,
  nullable: false,
  primaryKey: false,
  unique: false,
  ...o,
})
const pk = (name: string, type = 'serial', o: Partial<Column> = {}) =>
  col(name, type, { primaryKey: true, unique: true, ...o })
const fk = (column: string, refTable: string, refColumn: string): ForeignKey => ({ column, refTable, refColumn })
const tbl = (name: string, columns: Column[], foreignKeys: ForeignKey[] = [], extra: Partial<Table> = {}): Table => ({
  name,
  columns,
  foreignKeys,
  ...extra,
})

const placement: Table[] = [
  tbl('universities', [
    pk('university_id'),
    col('name', 'varchar', { maxLength: 120, unique: true }),
    col('city', 'varchar', { maxLength: 80 }),
    col('country', 'varchar', { maxLength: 60 }),
    col('established_year', 'integer', { check: 'established_year BETWEEN 1800 AND 2025' }),
    col('contact_email', 'varchar', { maxLength: 120 }),
  ]),
  tbl(
    'departments',
    [
      pk('department_id'),
      col('university_id', 'integer'),
      col('name', 'varchar', { maxLength: 100 }),
      col('head_name', 'varchar', { maxLength: 100, nullable: true }),
    ],
    [fk('university_id', 'universities', 'university_id')],
  ),
  tbl(
    'students',
    [
      pk('student_id', 'varchar', { maxLength: 12 }),
      col('university_id', 'integer'),
      col('department_id', 'integer'),
      col('full_name', 'varchar', { maxLength: 100 }),
      col('email', 'varchar', { maxLength: 120, unique: true }),
      col('phone', 'varchar', { maxLength: 20, nullable: true }),
      col('enrolment_year', 'integer', { check: 'enrolment_year >= 2015' }),
      col('is_active', 'boolean', { default: 'true' }),
    ],
    [fk('university_id', 'universities', 'university_id'), fk('department_id', 'departments', 'department_id')],
  ),
  tbl('placement_providers', [
    pk('provider_id'),
    col('name', 'varchar', { maxLength: 120, unique: true }),
    col('industry', 'varchar', { maxLength: 60 }),
    col('city', 'varchar', { maxLength: 80 }),
    col('contact_email', 'varchar', { maxLength: 120 }),
    col('phone', 'varchar', { maxLength: 20, nullable: true }),
  ]),
  tbl(
    'supervisors',
    [
      pk('supervisor_id', 'varchar', { maxLength: 12 }),
      col('provider_id', 'integer'),
      col('full_name', 'varchar', { maxLength: 100 }),
      col('email', 'varchar', { maxLength: 120, unique: true }),
      col('is_authorized', 'boolean', { default: 'true' }),
    ],
    [fk('provider_id', 'placement_providers', 'provider_id')],
  ),
  tbl(
    'placements',
    [
      pk('placement_id', 'varchar', { maxLength: 12 }),
      col('student_id', 'varchar', { maxLength: 12 }),
      col('provider_id', 'integer'),
      col('supervisor_id', 'varchar', { maxLength: 12 }),
      col('role_title', 'varchar', { maxLength: 100 }),
      col('start_date', 'date'),
      col('end_date', 'date', { nullable: true }),
      col('status', 'varchar', { maxLength: 20, enumValues: ['ACTIVE', 'COMPLETED', 'CANCELLED'] }),
    ],
    [
      fk('student_id', 'students', 'student_id'),
      fk('provider_id', 'placement_providers', 'provider_id'),
      fk('supervisor_id', 'supervisors', 'supervisor_id'),
    ],
  ),
  tbl(
    'timesheets',
    [
      pk('timesheet_id', 'varchar', { maxLength: 12 }),
      col('placement_id', 'varchar', { maxLength: 12 }),
      col('student_id', 'varchar', { maxLength: 12 }),
      col('week_start', 'date'),
      col('hours_worked', 'numeric', { check: 'hours_worked >= 0 AND hours_worked <= 60' }),
      col('status', 'varchar', {
        maxLength: 20,
        enumValues: ['SUBMITTED', 'PENDING', 'APPROVED', 'REJECTED', 'QUERIED'],
      }),
      col('notes', 'text', { nullable: true }),
      col('submitted_at', 'timestamp'),
    ],
    [fk('placement_id', 'placements', 'placement_id'), fk('student_id', 'students', 'student_id')],
  ),
  tbl(
    'timesheet_reviews',
    [
      pk('review_id'),
      col('timesheet_id', 'varchar', { maxLength: 12 }),
      col('supervisor_id', 'varchar', { maxLength: 12 }),
      col('decision', 'varchar', { maxLength: 20, enumValues: ['APPROVED', 'REJECTED', 'QUERIED'] }),
      col('reviewed_at', 'timestamp'),
      col('comment', 'text', { nullable: true }),
    ],
    [fk('timesheet_id', 'timesheets', 'timesheet_id'), fk('supervisor_id', 'supervisors', 'supervisor_id')],
  ),
]

const retail: Table[] = [
  tbl('customers', [
    pk('customer_id'),
    col('full_name', 'varchar', { maxLength: 100 }),
    col('email', 'varchar', { maxLength: 120, unique: true }),
    col('phone', 'varchar', { maxLength: 20, nullable: true }),
    col('city', 'varchar', { maxLength: 80 }),
    col('created_at', 'timestamp'),
  ]),
  tbl('products', [
    pk('product_id'),
    col('sku', 'varchar', { maxLength: 20, unique: true }),
    col('name', 'varchar', { maxLength: 120 }),
    col('category', 'varchar', { maxLength: 40 }),
    col('price', 'numeric', { check: 'price > 0' }),
    col('stock', 'integer'),
  ]),
  tbl(
    'orders',
    [
      pk('order_id'),
      col('customer_id', 'integer'),
      col('order_date', 'timestamp'),
      col('status', 'varchar', {
        maxLength: 20,
        enumValues: ['PLACED', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED'],
      }),
      col('total_amount', 'numeric'),
    ],
    [fk('customer_id', 'customers', 'customer_id')],
  ),
  tbl(
    'order_items',
    [
      pk('item_id'),
      col('order_id', 'integer'),
      col('product_id', 'integer'),
      col('quantity', 'integer', { check: 'quantity > 0' }),
      col('unit_price', 'numeric'),
    ],
    [fk('order_id', 'orders', 'order_id'), fk('product_id', 'products', 'product_id')],
  ),
  tbl(
    'payments',
    [
      pk('payment_id'),
      col('order_id', 'integer'),
      col('method', 'varchar', { maxLength: 20, enumValues: ['UPI', 'CARD', 'NETBANKING', 'COD'] }),
      col('amount', 'numeric'),
      col('paid_at', 'timestamp', { nullable: true }),
    ],
    [fk('order_id', 'orders', 'order_id')],
  ),
]

const mongo: Table[] = [
  tbl('users', [
    pk('_id', 'objectId'),
    col('name', 'string'),
    col('email', 'string', { unique: true }),
    col('plan', 'string', { enumValues: ['FREE', 'PRO', 'ENTERPRISE'] }),
    col('created_at', 'date'),
  ]),
  tbl('tickets', [
    pk('_id', 'objectId'),
    col('subject', 'string', { maxLength: 150 }),
    col('priority', 'string', { enumValues: ['LOW', 'MEDIUM', 'HIGH'] }),
    col('status', 'string', { enumValues: ['OPEN', 'IN_PROGRESS', 'CLOSED'] }),
    col('opened_at', 'date'),
  ]),
  tbl('audit_logs', [pk('_id', 'objectId', { missing: false })], [], { needsDefinition: true }),
]

export function buildSchema(targetId: string): Schema {
  const base = {
    targetId,
    extractedAt: new Date().toISOString(),
  }
  switch (targetId) {
    case 'mysql-retail-test':
      return {
        ...base,
        dbType: 'mysql',
        database: 'retail_test_db',
        tables: retail,
        warnings: ['MySQL check constraints below 8.0.16 are parsed but not enforced by the engine.'],
        source: 'boomi-jdbc',
      }
    case 'mongo-support-test':
      return {
        ...base,
        dbType: 'mongodb',
        database: 'support_test_db',
        tables: mongo,
        warnings: [
          'MongoDB metadata cannot reveal relationships. Cross-collection references are shown as missing, not guessed.',
          'Collection "audit_logs" has no schema validator. Provide a JSON Schema or define its fields manually.',
        ],
        source: 'boomi-pymongo',
      }
    default:
      return {
        ...base,
        dbType: 'postgresql',
        database: 'placement_test_db',
        tables: placement,
        warnings: [
          'Check constraints are read from pg_constraint; only simple range checks are validated automatically.',
        ],
        source: 'boomi-jdbc',
      }
  }
}
