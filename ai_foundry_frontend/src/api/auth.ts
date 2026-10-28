// src/api/auth.ts
/**
 * HTTP Basic credentials shared by every API call (same pair the backend and Boomi use).
 * They live in sessionStorage only (cleared when the tab closes) and are never logged.
 * For local development they may be pre-set with VITE_API_USERNAME / VITE_API_PASSWORD; anything built into a
 * public bundle is visible to every visitor, so production should rely on the sign-in form instead.
 */
const KEY = 'atom_basic'

const b64 = (s: string) => {
  const bytes = new TextEncoder().encode(s)
  let bin = ''
  bytes.forEach((b) => (bin += String.fromCharCode(b)))
  return btoa(bin)
}

export function setCredentials(username: string, password: string) {
  try {
    sessionStorage.setItem(KEY, b64(`${username}:${password}`))
  } catch {
    /* storage unavailable: credentials only last for this call chain */
  }
}

export function clearCredentials() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

export function authHeader(): Record<string, string> {
  let token: string | null = null
  try {
    token = sessionStorage.getItem(KEY)
  } catch {
    /* ignore */
  }
  if (!token) {
    const u = import.meta.env.VITE_API_USERNAME as string | undefined
    const p = import.meta.env.VITE_API_PASSWORD as string | undefined
    if (u && p) token = b64(`${u}:${p}`)
  }
  return token ? { Authorization: `Basic ${token}` } : {}
}

export const AUTH_EVENT = 'atom-auth-required'
