// src/api/types.ts
import type {
  ApprovedTarget,
  Blueprint,
  ConnectionRequest,
  ConnectionResult,
  ExportFormat,
  Job,
  ParsedCollection,
  JobConfig,
  LoadJob,
  LoadPlan,
  PreviewPage,
  Schema,
} from '../types'

export interface Api {
  mode: 'mock' | 'http'
  listTargets(): Promise<ApprovedTarget[]>
  deleteTarget?(id: string): Promise<void>
  /** Resolves when the stored Basic credentials are accepted; rejects (and signals sign-in) otherwise. */
  checkAuth?(): Promise<void>
  testConnection(req: ConnectionRequest): Promise<ConnectionResult>
  /** Boomi Process A: metadata only, request carries a target id and never credentials. */
  fetchSchema(targetId: string): Promise<Schema>
  planBlueprint(schema: Schema, config: JobConfig): Promise<Blueprint>
  /** Reads a Postman collection / OpenAPI file and matches its requests to tables. Needs the backend. */
  parseCollection(text: string, schema: Schema): Promise<ParsedCollection>
  createJob(schema: Schema, config: JobConfig): Promise<{ jobId: string }>
  getJob(jobId: string): Promise<Job>
  getPreview(jobId: string, table: string, page: number, pageSize: number): Promise<PreviewPage>
  generateMissing(jobId: string): Promise<Job>
  exportFile(jobId: string, format: ExportFormat): Promise<{ blob: Blob; filename: string }>
  getLoadPlan(jobId: string, targetId: string): Promise<LoadPlan>
  startLoad(jobId: string, targetId: string): Promise<{ loadId: string }>
  getLoad(loadId: string): Promise<LoadJob>
}
