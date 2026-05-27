import { useMemo } from "react"
import type { SessionState } from "@/hooks/useRunState"
import { formatDuration } from "@/lib/duration"
import { formatUsage } from "@/lib/usage"
import { Stepper, type Step, type StepState } from "@/components/ui/stepper"

interface Props {
  sessions: SessionState[]
  issueId: string | null
  outcomes: Record<string, string>
  selectedSessionId: string | null
  onSelect: (sessionId: string) => void
}

function sessionState(s: SessionState): StepState {
  if (s.completed_at === null) return "running"
  // status may carry the outcome category; absent here means "done"
  return "done"
}

export function PhasesPanel({ sessions, issueId, outcomes, selectedSessionId, onSelect }: Props) {
  const steps: Step[] = useMemo(() => {
    if (issueId === null) return []
    return sessions
      .filter((s) => s.issue_id === issueId)
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
      .map((s) => ({
        id: s.session_id,
        state: sessionState(s),
        name: s.state,
        outcome: outcomes[s.session_id],
        duration: formatDuration(s.started_at, s.completed_at),
        usage: formatUsage(s.usage),
        progress: s.progress,
        progressText: s.status ?? null,
        active: s.session_id === selectedSessionId,
        onClick: () => onSelect(s.session_id),
      }))
  }, [sessions, issueId, outcomes, selectedSessionId, onSelect])

  if (issueId === null) return null
  if (steps.length === 0) {
    return (
      <div className="px-2 py-1 text-[12px] text-[var(--fg-muted)] italic">No phases yet.</div>
    )
  }

  return <Stepper steps={steps} />
}
