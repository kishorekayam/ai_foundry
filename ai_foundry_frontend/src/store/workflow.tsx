import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { ConnectionResult, GenMode, JobConfig, Schema } from '../types'

/**
 * Holds the journey state. Only the approved target id is kept for a connection:
 * passwords and URIs are never stored here, logged, or sent anywhere except the connection test.
 */
export interface Workflow {
  connection?: ConnectionResult
  schema?: Schema
  mode?: GenMode
  config?: JobConfig
  jobId?: string
  downloads: string[]
  loadId?: string
}

interface Ctx extends Workflow {
  update: (p: Partial<Workflow>) => void
  reset: () => void
  addDownload: (name: string) => void
}

const WorkflowContext = createContext<Ctx | null>(null)

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Workflow>({ downloads: [] })
  const value = useMemo<Ctx>(
    () => ({
      ...state,
      update: (p) => setState((s) => ({ ...s, ...p })),
      reset: () => setState({ downloads: [] }),
      addDownload: (name) => setState((s) => ({ ...s, downloads: s.downloads.includes(name) ? s.downloads : [...s.downloads, name] })),
    }),
    [state],
  )
  return <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>
}

export function useWorkflow() {
  const c = useContext(WorkflowContext)
  if (!c) throw new Error('useWorkflow must be used inside WorkflowProvider')
  return c
}
