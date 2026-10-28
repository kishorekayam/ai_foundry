// src/api/index.ts
import { httpApi } from './httpApi'
import { mockApi } from './mock/mockApi'
import type { Api } from './types'

/** Set VITE_API_BASE to the FastAPI origin to use the real backend; otherwise the in-browser engine runs. */
export const api: Api = import.meta.env.VITE_API_BASE ? httpApi : mockApi
export type { Api }
