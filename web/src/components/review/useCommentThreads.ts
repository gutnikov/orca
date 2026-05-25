import { useCallback, useEffect, useRef, useState } from "react"

function newOptimisticId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `optimistic-${crypto.randomUUID()}`
  }
  return `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export interface ThreadMessage {
  id: string
  role: "user" | "agent"
  body: string
  timestamp: string
}

interface ServerThread {
  id: string
  comment_id: string
  messages: ThreadMessage[]
  agent_last_reviewed_at: string | null
}

interface ServerCommentWithThread {
  id: string
  file: string
  line: number | null
  body: string
  thread: ServerThread | null
}

const POLL_INTERVAL_MS = 5000
const REVIEWING_THRESHOLD_MS = 3000

export interface ThreadView {
  messages: ThreadMessage[]
  /** True when the latest msg is user-authored and >= 3 s old — heuristic for "Orca is reviewing…". */
  agentReviewing: boolean
}

/**
 * Polls /comments every 5 s while the debug pause is active. Exposes per-comment
 * thread state and an optimistic reply() that POSTs a user message.
 */
export function useCommentThreads(runId: string, issueId: string) {
  const [byCommentId, setByCommentId] = useState<Record<string, ServerThread>>({})
  const [tick, setTick] = useState(0)
  const pollTimerRef = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/issues/${issueId}/comments`)
      if (!res.ok) return
      const data: { comments: ServerCommentWithThread[] } = await res.json()
      setByCommentId(() => {
        const next: Record<string, ServerThread> = {}
        for (const c of data.comments) {
          if (c.thread !== null) next[c.id] = c.thread
        }
        return next
      })
    } catch {
      // ignore — best-effort
    }
  }, [runId, issueId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current)
    }
    pollTimerRef.current = window.setInterval(refresh, POLL_INTERVAL_MS)
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [refresh])

  // Drive the agentReviewing heuristic by re-rendering once per second while
  // any thread has a pending user message at the tail.
  useEffect(() => {
    const hasPending = Object.values(byCommentId).some((t) =>
      t.messages.length > 0 && t.messages[t.messages.length - 1].role === "user"
    )
    if (!hasPending) return
    const id = window.setInterval(() => setTick((v) => v + 1), 1000)
    return () => window.clearInterval(id)
  }, [byCommentId])

  const threadFor = useCallback((commentId: string): ThreadView | undefined => {
    const t = byCommentId[commentId]
    if (!t || t.messages.length === 0) return undefined
    const last = t.messages[t.messages.length - 1]
    const agentReviewing =
      last.role === "user" &&
      Date.now() - new Date(last.timestamp).getTime() >= REVIEWING_THRESHOLD_MS
    void tick // reference for re-render trigger
    return { messages: t.messages, agentReviewing }
  }, [byCommentId, tick])

  const reply = useCallback(async (commentId: string, body: string) => {
    // Optimistic local append so the user sees their reply instantly
    setByCommentId((prev) => {
      const existing = prev[commentId] ?? { id: "", comment_id: commentId, messages: [], agent_last_reviewed_at: null }
      return {
        ...prev,
        [commentId]: {
          ...existing,
          messages: [
            ...existing.messages,
            { id: newOptimisticId(), role: "user" as const, body, timestamp: new Date().toISOString() },
          ],
        },
      }
    })
    try {
      await fetch(`/api/runs/${runId}/issues/${issueId}/comments/${commentId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: "user", body }),
      })
      void refresh()
    } catch {
      // ignore — next poll will re-sync
    }
  }, [runId, issueId, refresh])

  return { threadFor, reply }
}
