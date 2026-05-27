import { useMemo } from "react"
import { Loader2, CheckCircle2 } from "lucide-react"
import type { SessionState } from "@/hooks/useRunState"
import { formatDuration } from "@/lib/duration"
import { cn } from "@/lib/utils"

interface Props {
  sessions: SessionState[]
  issueId: string | null
  outcomes: Record<string, string>
  selectedSessionId: string | null
  onSelect: (sessionId: string) => void
}

export function PhasesPanel({ sessions, issueId, outcomes, selectedSessionId, onSelect }: Props) {
  const filtered = useMemo(
    () =>
      issueId
        ? sessions
            .filter((s) => s.issue_id === issueId)
            .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
        : [],
    [sessions, issueId],
  )

  if (issueId === null) {
    return null
  }
  if (filtered.length === 0) {
    return (
      <div className="px-2 py-1 text-[12px] text-muted-foreground italic">
        No phases yet.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-0.5">
      {filtered.map((s) => {
        const isSelected = s.session_id === selectedSessionId
        const active = s.completed_at === null
        const outcome = outcomes[s.session_id]
        const duration = formatDuration(s.started_at, s.completed_at)
        const progress = typeof s.progress === "number" ? Math.max(0, Math.min(1, s.progress)) : null
        return (
          <button
            type="button"
            key={s.session_id}
            onClick={() => onSelect(s.session_id)}
            className={cn(
              "w-full text-left rounded-md px-2 py-1.5 transition-colors",
              isSelected
                ? "bg-accent/15 border-l-2 border-primary"
                : "hover:bg-muted",
            )}
          >
            <div className="flex items-center gap-1.5 text-[12px]">
              {active ? (
                <Loader2 size={12} className="animate-spin text-[#d4a064]" />
              ) : (
                <CheckCircle2 size={12} className="text-emerald-500" />
              )}
              <span className="font-mono text-foreground truncate flex-1">{s.state}</span>
              {duration && (
                <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
                  {duration}
                </span>
              )}
            </div>
            {outcome && (
              <div className="mt-0.5 text-[10px] text-muted-foreground italic truncate">
                {outcome}
              </div>
            )}
            {progress !== null && active && (
              <div className="mt-1 h-0.5 w-full rounded bg-muted overflow-hidden">
                <div
                  className="h-full bg-[#d4a064] transition-[width] duration-500"
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}
