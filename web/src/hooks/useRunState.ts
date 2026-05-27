import { useCallback, useState } from "react"
import { usePollInterval } from "./usePollInterval"

export interface IssueFields {
  title?: string
  body?: string
  [key: string]: unknown
}

export interface IssueState {
  type: string
  fields: IssueFields
  state: string
  worker_active: boolean
  decomposed_from: string | null
  depends_on: string[]
  failure_count: number
  hop_count: number
  visit_counts: Record<string, number>
  debug_pending?: boolean
  modify_pending?: boolean
  event_log?: Array<{ type: string; data: Record<string, unknown> }>
}

export interface UsageState {
  source: string
  model?: string
  external_session_id?: string
  cost_usd?: number
  cost_kind?: "exact" | "estimated" | string
  total_tokens?: number
  updated_at?: string
  tokens?: {
    input: number
    output: number
    reasoning: number
    cache_read: number
    cache_write: number
  }
}

export interface SessionState {
  session_id: string
  issue_id: string
  state: string
  started_at: string
  completed_at: string | null
  status?: string
  progress?: number
  progress_updated_at?: string | null
  log_path?: string
  worker_kind?: string
  model?: string
  effort?: string
  usage_marker?: string
  usage?: UsageState
}

export interface RunState {
  run_id: string
  status?: string
  state: { issues: Record<string, IssueState> }
  sessions: SessionState[]
}

export interface UseRunStateResult {
  data: RunState | null
  error: string | null
  refetch: () => Promise<void>
}

export function useRunState(runId: string, intervalMs = 1500): UseRunStateResult {
  const [data, setData] = useState<RunState | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetcher = useCallback(async () => {
    try {
      const r = await fetch(`/api/runs/${runId}`)
      if (!r.ok) {
        setError(`HTTP ${r.status}`)
        return
      }
      const json = (await r.json()) as RunState
      setData(json)
      setError(null)
    } catch (exc) {
      setError(String(exc))
    }
  }, [runId])

  usePollInterval(fetcher, intervalMs)

  return { data, error, refetch: fetcher }
}
