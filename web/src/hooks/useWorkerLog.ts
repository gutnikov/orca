import { useCallback, useEffect, useRef, useState } from "react"
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
  const abortRef = useRef<AbortController | null>(null)

  // Clear stale text immediately when the user switches issue/session so the
  // viewer doesn't keep showing the old log for up to one poll interval, and
  // abort any in-flight fetch so its stale response can't overwrite the new one.
  useEffect(() => {
    abortRef.current?.abort()
    setText("")
    setError(null)
    return () => {
      abortRef.current?.abort()
    }
  }, [issueId, sessionId])

  const fetcher = useCallback(async () => {
    if (!issueId) {
      setText("")
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const params = new URLSearchParams({ tail: String(tail) })
      if (sessionId) params.set("session_id", sessionId)
      const r = await fetch(`/api/runs/${runId}/logs/${issueId}?${params.toString()}`, {
        signal: controller.signal,
      })
      if (!r.ok) {
        setError(`HTTP ${r.status}`)
        return
      }
      const body = await r.text()
      if (controller.signal.aborted) return
      setText(body)
      setError(null)
    } catch (exc) {
      if (controller.signal.aborted) return
      setError(String(exc))
    }
  }, [runId, issueId, sessionId, tail])

  usePollInterval(fetcher, intervalMs, issueId !== null)

  return { text, error, refetch: fetcher }
}
