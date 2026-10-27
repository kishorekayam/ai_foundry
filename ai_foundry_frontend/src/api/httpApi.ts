import { AUTH_EVENT, authHeader } from './auth'
import type { Api } from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

/** Anonymous per-browser id that owns this browser's saved connections. */
function clientId() {
  try {
    let id = localStorage.getItem('atom_client_id')
    if (!id) {
      id = (crypto.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36)).replace(/[^A-Za-z0-9_-]/g, '')
      localStorage.setItem('atom_client_id', id)
    }
    return id
  } catch {
    return 'session' + Math.random().toString(36).slice(2, 12)
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId(), ...authHeader(), ...init?.headers },
  })
  if (res.status === 401) {
    window.dispatchEvent(new Event(AUTH_EVENT))
    throw new Error('Sign in required.')
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      msg = (await res.json()).detail ?? msg
    } catch {
      /* ignore */
    }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) => req<T>(path, { method: 'POST', body: JSON.stringify(body) })

async function file(path: string) {
  const res = await fetch(`${BASE}${path}`, { headers: { 'X-Client-Id': clientId(), ...authHeader() } })
  if (res.status === 401) {
    window.dispatchEvent(new Event(AUTH_EVENT))
    throw new Error('Sign in required.')
  }
  if (!res.ok) throw new Error(`Download failed (${res.status})`)
  const cd = res.headers.get('content-disposition') ?? ''
  return { blob: await res.blob(), filename: /filename="?([^";]+)"?/.exec(cd)?.[1] ?? 'atom_foundry_export' }
}

/**
 * FastAPI contract. Credentials go to /connections/test only, over HTTPS, and are never persisted by the UI.
 * The browser never talks to Boomi or the LLM directly.
 */
export const httpApi: Api = {
  mode: 'http',
  checkAuth: async () => {
    await req('/api/auth/check')
  },
  listTargets: () => req('/api/targets'),
  deleteTarget: async (id) => {
    await req(`/api/targets/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
  testConnection: (r) => post('/api/connections/test', r),
  fetchSchema: (targetId) => post('/api/schema', { targetId }),
  planBlueprint: (schema, config) => post('/api/plan', { schema, config }),
  parseCollection: (text, schema) => post('/api/collection/parse', { text, schema }),
  createJob: (schema, config) => post('/api/jobs', { schema, config }),
  getJob: (id) => req(`/api/jobs/${id}`),
  getPreview: (id, table, page, pageSize) => req(`/api/jobs/${id}/preview?table=${encodeURIComponent(table)}&page=${page}&page_size=${pageSize}`),
  generateMissing: (id) => post(`/api/jobs/${id}/generate-missing`, {}),
  exportFile: (id, format) => file(`/api/jobs/${id}/export?format=${format}`),
  getLoadPlan: (id, targetId) => post(`/api/jobs/${id}/load-plan`, { targetId }),
  startLoad: (id, targetId) => post(`/api/jobs/${id}/load`, { targetId, approved: true }),
  getLoad: (loadId) => req(`/api/loads/${loadId}`),
}
