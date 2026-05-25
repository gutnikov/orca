import { useCallback, useEffect, useRef, useState } from "react"

interface ServerQuestion {
  id: string
  client_comment_id: string
  file: string
  line: number | null
  body: string
  answer: string | null
}

interface QuestionState {
  questionId: string
  answer: string | null
}

const POLL_INTERVAL_MS = 5000

/**
 * Manages the lifecycle of "Ask agent" review questions for a debug pause.
 *
 * Comments are tracked client-side (localStorage drafts) and only POSTed
 * to the server when the user clicks "Ask agent". This hook owns:
 *  - asking a question (POST → store questionId locally by client_comment_id)
 *  - polling the server for answers while there are unanswered questions
 *  - hydrating from server on mount so an answer that arrived in another
 *    tab / after a reload still shows up under the matching comment.
 */
export function useDebugQuestions(runId: string, issueId: string) {
  // Keyed by client_comment_id → questionId + (latest) answer
  const [byCommentId, setByCommentId] = useState<Record<string, QuestionState>>({})
  const pollTimerRef = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/issues/${issueId}/debug/questions`)
      if (!res.ok) return
      const data: { questions: ServerQuestion[] } = await res.json()
      setByCommentId((prev) => {
        const next: Record<string, QuestionState> = { ...prev }
        for (const q of data.questions) {
          next[q.client_comment_id] = { questionId: q.id, answer: q.answer }
        }
        return next
      })
    } catch {
      // ignore — debug review is best-effort
    }
  }, [runId, issueId])

  // Hydrate on mount.
  useEffect(() => {
    void refresh()
  }, [refresh])

  // Poll while any tracked question is unanswered.
  useEffect(() => {
    const hasPending = Object.values(byCommentId).some((q) => q.answer === null)
    if (!hasPending) {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
      return
    }
    if (pollTimerRef.current !== null) return
    pollTimerRef.current = window.setInterval(refresh, POLL_INTERVAL_MS)
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [byCommentId, refresh])

  const ask = useCallback(
    async (commentId: string, file: string, line: number | null, body: string) => {
      // Optimistic: mark as pending immediately so the spinner shows.
      setByCommentId((prev) => ({ ...prev, [commentId]: { questionId: "", answer: null } }))
      try {
        const res = await fetch(`/api/runs/${runId}/issues/${issueId}/debug/questions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_comment_id: commentId, file, line, body }),
        })
        if (!res.ok) {
          setByCommentId((prev) => {
            const next = { ...prev }
            delete next[commentId]
            return next
          })
          return
        }
        const data: { question_id: string; answer: string | null } = await res.json()
        setByCommentId((prev) => ({
          ...prev,
          [commentId]: { questionId: data.question_id, answer: data.answer },
        }))
      } catch {
        setByCommentId((prev) => {
          const next = { ...prev }
          delete next[commentId]
          return next
        })
      }
    },
    [runId, issueId],
  )

  return { byCommentId, ask, refresh }
}
