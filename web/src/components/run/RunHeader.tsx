import { useState } from "react"
import { toast } from "sonner"
import type { IssueState } from "@/hooks/useRunState"
import { Button } from "@/components/ui/button"
import { StatusPill, type StatusKind } from "@/components/ui/status-pill"
import { UnblockDialog } from "./UnblockDialog"
import { StopResumeDropButtons } from "./StopResumeDropButtons"
import { cn } from "@/lib/utils"

type Tab = "detail" | "session" | "result"

interface Props {
  runId: string
  status: string | undefined
  debugMode: boolean
  elapsed: string
  issueCount: number
  doneCount: number
  selectedIssueId: string | null
  selectedIssue: IssueState | null
  activeTab: Tab
  setTab: (t: Tab) => void
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
  activeTab,
  setTab,
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
    const r = await fetch(`/api/runs/${runId}/retry/${selectedIssueId}`, { method: "POST" })
    if (!r.ok) {
      const body = (await r.json().catch(() => ({}))) as { error?: string }
      toast.error(body.error ?? `HTTP ${r.status}`)
      return
    }
    toast.success("Retry requested")
    onChange()
  }

  return (
    <div className="border-b border-[var(--border)] bg-[var(--canvas)]">
      <div className="px-5 pt-4 pb-2">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="font-mono text-[20px] font-semibold text-[var(--fg)]">{runId}</h1>
          <StatusPill kind={statusToKind(status)} />
          {debugMode && <StatusPill kind="attention" label="debug" pulse={false} size="sm" />}
        </div>
        <div className="mt-1.5 flex items-center gap-3 text-[12px] text-[var(--fg-muted)] flex-wrap">
          {elapsed && <span className="tabular-nums">started {elapsed} ago</span>}
          <span className="text-[var(--border)]">·</span>
          <span>
            {doneCount} of {issueCount} done
          </span>
        </div>
      </div>
      <nav className="px-5 flex items-center gap-1">
        {(["detail", "session", "result"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              "px-3 py-2 text-[13px] capitalize border-b-2 -mb-px transition-colors",
              activeTab === t
                ? "border-[var(--accent-warm)] text-[var(--fg)] font-medium"
                : "border-transparent text-[var(--fg-muted)] hover:text-[var(--fg)]",
            )}
          >
            {t}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1.5 py-1.5">
          <Button size="sm" onClick={() => void retry()} disabled={!retryEnabled}>
            Retry
          </Button>
          <Button size="sm" onClick={() => setUnblockOpen(true)} disabled={!unblockEnabled}>
            Unblock…
          </Button>
          <StopResumeDropButtons runId={runId} status={status} onChange={onChange} />
        </div>
      </nav>

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
