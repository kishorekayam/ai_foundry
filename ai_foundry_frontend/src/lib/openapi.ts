// src/lib/openapi.ts
import * as yaml from 'js-yaml'

export interface Endpoint {
  method: string
  path: string
  summary: string
}

export interface ParsedSpec {
  title: string
  baseUrl: string
  endpoints: Endpoint[]
}

const METHODS = ['get', 'post', 'put', 'patch', 'delete']

export function parseOpenApi(text: string): ParsedSpec {
  const doc = (text.trim().startsWith('{') ? JSON.parse(text) : yaml.load(text)) as Record<string, any>
  if (!doc || typeof doc !== 'object' || !doc.paths) throw new Error('No "paths" found. Is this an OpenAPI / Swagger document?')
  const endpoints: Endpoint[] = []
  for (const [path, item] of Object.entries<Record<string, any>>(doc.paths)) {
    for (const m of METHODS) {
      if (item?.[m]) endpoints.push({ method: m.toUpperCase(), path, summary: item[m].summary ?? item[m].operationId ?? '' })
    }
  }
  const server = doc.servers?.[0]?.url ?? (doc.host ? `${doc.schemes?.[0] ?? 'https'}://${doc.host}${doc.basePath ?? ''}` : '')
  return { title: doc.info?.title ?? 'API', baseUrl: server, endpoints }
}
