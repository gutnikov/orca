import { useCallback, useState } from "react"
import { usePollInterval } from "./usePollInterval"

export interface UseWorkerLogResult {
  text: string
  error: string | null
  refetch: () => Promise<void>
}

export function useWorkerLog(
  runId: string,
  issueId: string | null,
  sessionId: string | null,
  tail = 500,
  intervalMs = 1500,
): UseWorkerLogResult {
  const [text, setText] = useState<string>("")
  const [error, setError] = useState<string | null>(null)

  const fetcher = useCallback(async () => {
    if (!issueId) {
      setText("")
      return
    }
    try {
      const params = new URLSearchParams({ tail: String(tail) })
      if (sessionId) params.set("session_id", sessionId)
      const r = await fetch(`/api/runs/${runId}/logs/${issueId}?${params.toString()}`)
      if (!r.ok) {
        setError(`HTTP ${r.status}`)
        return
      }
      setText(await r.text())
      setError(null)
    } catch (exc) {
      setError(String(exc))
    }
  }, [runId, issueId, sessionId, tail])

  usePollInterval(fetcher, intervalMs, issueId !== null)

  return { text, error, refetch: fetcher }
}
