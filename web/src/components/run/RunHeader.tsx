import { useState } from "react"
import { toast } from "sonner"
import type { IssueState } from "@/hooks/useRunState"
import { Button } from "@/components/ui/button"
import { StatusPill, type StatusKind } from "@/components/ui/status-pill"
import { UnblockDialog } from "./UnblockDialog"
import { StopResumeDropButtons } from "./StopResumeDropButtons"

interface Props {
  runId: string
  status: string | undefined
  debugMode: boolean
  elapsed: string
  issueCount: number
  doneCount: number
  selectedIssueId: string | null
  selectedIssue: IssueState | null
  onChange: () => void
}

function statusToKind(status: string | undefined): StatusKind {
  if (status === "running") return "running"
  if (status === "completed") return "completed"
  if (status === "stopped") return "stopped"
  if (status === "errored") return "errored"
  return "draft"
}

export function RunHeader({
  runId,
  status,
  debugMode,
  elapsed,
  issueCount,
  doneCount,
  selectedIssueId,
  selectedIssue,
  onChange,
}: Props) {
  const [unblockOpen, setUnblockOpen] = useState(false)

  const retryEnabled =
    selectedIssue !== null &&
    selectedIssueId !== null &&
    selectedIssue.failure_count > 0 &&
    !selectedIssue.worker_active

  const unblockEnabled =
    selectedIssue !== null && selectedIssueId !== null && selectedIssue.worker_active

  const retry = async () => {
    if (!selectedIssueId) return
    try {
      const r = await fetch(`/api/runs/${runId}/retry/${selectedIssueId}`, { method: "POST" })
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { error?: string }
        toast.error(body.error ?? `HTTP ${r.status}`)
        return
      }
      toast.success("Retry requested")
      onChange()
    } catch (exc) {
      toast.error(exc instanceof Error ? exc.message : String(exc))
    }
  }

  return (
    <div className="border-b border-[var(--border)] bg-[var(--canvas)]">
      <div className="px-5 py-3 flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="font-mono text-[20px] font-semibold text-[var(--fg)]">{runId}</h1>
            <StatusPill kind={statusToKind(status)} />
            {debugMode && <StatusPill kind="attention" label="debug" pulse={false} size="sm" />}
          </div>
          <div className="mt-1 flex items-center gap-3 text-[12px] text-[var(--fg-muted)] flex-wrap">
            {elapsed && <span className="tabular-nums">started {elapsed} ago</span>}
            <span className="text-[var(--border)]">·</span>
            <span>
              {doneCount} of {issueCount} done
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Button size="sm" onClick={() => void retry()} disabled={!retryEnabled}>
            Retry
          </Button>
          <Button size="sm" onClick={() => setUnblockOpen(true)} disabled={!unblockEnabled}>
            Unblock…
          </Button>
          <StopResumeDropButtons runId={runId} status={status} onChange={onChange} />
        </div>
      </div>

      {selectedIssueId && (
        <UnblockDialog
          runId={runId}
          issueId={selectedIssueId}
          open={unblockOpen}
          onOpenChange={setUnblockOpen}
          onSent={onChange}
        />
      )}
    </div>
  )
}
