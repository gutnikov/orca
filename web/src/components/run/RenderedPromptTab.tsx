import { useEffect, useState } from "react"
import type { SessionState } from "@/hooks/useRunState"
import { estimatePromptTokens } from "@/lib/promptTokens"
import { formatTokens } from "@/lib/usage"
import { cn } from "@/lib/utils"

interface Props {
  runId: string
  session: SessionState | null
  onPromptTokenCountChange?: (sessionId: string, tokenCount: number | null) => void
}

export function RenderedPromptTab({ runId, session, onPromptTokenCountChange }: Props) {
  const sessionId = session?.session_id ?? null
  const [prompt, setPrompt] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) {
      setPrompt("")
      setError(null)
      setLoading(false)
      return
    }

    const controller = new AbortController()
    setPrompt("")
    setLoading(true)
    setError(null)
    fetch(`/api/runs/${runId}/sessions/${encodeURIComponent(sessionId)}/prompt`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 404) return ""
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.text()
      })
      .then((text) => {
        setPrompt(text)
        onPromptTokenCountChange?.(sessionId, text ? estimatePromptTokens(text) : null)
      })
      .catch((exc: unknown) => {
        if (controller.signal.aborted) return
        setPrompt("")
        setError(String(exc))
        onPromptTokenCountChange?.(sessionId, null)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => {
      controller.abort()
    }
  }, [onPromptTokenCountChange, runId, sessionId])

  if (!session) {
    return (
      <div className="px-6 py-8 text-center text-sm text-muted-foreground italic">
        No phase selected.
      </div>
    )
  }

  if (loading && !prompt) {
    return (
      <div className="px-6 py-8 text-center text-sm text-muted-foreground italic">
        Loading prompt…
      </div>
    )
  }

  if (error) {
    return (
      <div className="m-4 text-[12px] text-[var(--danger)] bg-[var(--danger)]/5 border border-[var(--danger)]/40 rounded-md px-3 py-1.5">
        {error}
      </div>
    )
  }

  if (!prompt) {
    return (
      <div className="px-6 py-8 text-center text-sm text-muted-foreground italic">
        No rendered prompt available for this session.
      </div>
    )
  }

  const promptTokens = estimatePromptTokens(prompt)

  return (
    <div className="h-full min-h-0 p-4 flex flex-col">
      <div className="mb-2 flex items-center justify-between gap-3 text-[12px]">
        <div className="font-medium text-[var(--fg)]">Rendered prompt</div>
        {promptTokens > 0 && (
          <div
            className="shrink-0 text-[var(--fg-muted)]"
            title="Estimated from rendered prompt length; actual CLI tokenizer counts can vary by model."
          >
            ~{formatTokens(promptTokens)} tok
          </div>
        )}
      </div>
      <pre
        className={cn(
          "min-h-0 flex-1 overflow-auto rounded-md border border-[var(--border)] bg-[var(--surface)]",
          "px-4 py-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap",
          "text-[var(--fg)]/90",
        )}
      >
        {prompt}
      </pre>
    </div>
  )
}
