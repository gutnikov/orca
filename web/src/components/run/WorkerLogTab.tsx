import { useEffect, useRef, useState } from "react"
import { renderAnsi } from "@/lib/ansi"
import { formatDuration } from "@/lib/duration"
import type { SessionState } from "@/hooks/useRunState"
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
    <div className="flex flex-col h-full">
      {session && (
        <div className="px-4 py-2 border-b border-border flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="font-mono text-foreground">{session.state}</span>
          {session.started_at && (
            <span className="tabular-nums">{formatDuration(session.started_at, session.completed_at)}</span>
          )}
          {outcome && (
            <span className="italic truncate">{outcome}</span>
          )}
          <span className="ml-auto flex items-center gap-3">
            {!largeTail && (
              <button
                type="button"
                onClick={onIncreaseTail}
                className="underline hover:text-foreground"
              >
                view 2000 lines
              </button>
            )}
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={stickToBottom}
                onChange={(e) => setStickToBottom(e.target.checked)}
                className="accent-primary"
              />
              <span>follow</span>
            </label>
          </span>
        </div>
      )}
      {error && (
        <div className="px-4 py-2 text-[12px] text-destructive bg-destructive/5">
          {error}
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className={cn(
          "flex-1 min-h-0 overflow-y-auto px-4 py-3 font-mono text-[11px]",
          "leading-relaxed whitespace-pre-wrap text-foreground/85 bg-background",
        )}
      >
        {text ? renderAnsi(text) : (
          <span className="text-muted-foreground italic">No log yet.</span>
        )}
      </div>
    </div>
  )
}
