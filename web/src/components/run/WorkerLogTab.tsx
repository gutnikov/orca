import { useEffect, useRef, useState } from "react"
import { renderAnsi } from "@/lib/ansi"
import { formatDuration } from "@/lib/duration"
import { formatUsage } from "@/lib/usage"
import type { SessionState } from "@/hooks/useRunState"
import { StatusPill } from "@/components/ui/status-pill"
import { cn } from "@/lib/utils"

interface Props {
  text: string
  error: string | null
  session: SessionState | null
  outcome: string | undefined
  onIncreaseTail: () => void
  largeTail: boolean
}

export function WorkerLogTab({ text, error, session, outcome, onIncreaseTail, largeTail }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [stickToBottom, setStickToBottom] = useState(true)
  const usage = formatUsage(session?.usage)

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !stickToBottom) return
    el.scrollTop = el.scrollHeight
  }, [text, stickToBottom])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setStickToBottom(distFromBottom < 30)
  }

  return (
    <div className="flex flex-col h-full p-4 gap-2">
      {session && (
        <div className="flex items-center gap-2 text-[11.5px] text-[var(--fg-muted)]">
          <StatusPill
            kind={session.completed_at === null ? "running" : "completed"}
            label={session.state}
            size="sm"
          />
          {session.started_at && (
            <span className="tabular-nums">
              {formatDuration(session.started_at, session.completed_at)}
            </span>
          )}
          {usage && <span className="tabular-nums text-[var(--fg-subtle)]">{usage}</span>}
          {outcome && (
            <span className="italic truncate text-[var(--fg-subtle)]">{outcome}</span>
          )}
        </div>
      )}
      {error && (
        <div className="text-[12px] text-[var(--danger)] bg-[var(--danger)]/5 border border-[var(--danger)]/40 rounded-md px-3 py-1.5">
          {error}
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className={cn(
          "flex-1 min-h-0 overflow-y-auto",
          "rounded-md border border-[var(--border)] bg-[var(--surface)]",
          "px-4 py-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap",
          "text-[var(--fg)]/90",
        )}
      >
        {text ? renderAnsi(text) : (
          <span className="text-[var(--fg-muted)] italic">No log yet.</span>
        )}
      </div>
      <div className="flex items-center gap-4 text-[11px] text-[var(--fg-subtle)]">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={stickToBottom}
            onChange={(e) => setStickToBottom(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span>follow output</span>
        </label>
        {!largeTail && (
          <button
            type="button"
            onClick={onIncreaseTail}
            className="text-[var(--accent-fg)] hover:underline"
          >
            view 2000 lines
          </button>
        )}
        <span className="ml-auto tabular-nums">last update just now</span>
      </div>
    </div>
  )
}
