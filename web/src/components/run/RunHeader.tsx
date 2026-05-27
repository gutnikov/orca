import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { toast } from "sonner"
import { ArrowLeft } from "lucide-react"
import type { IssueState } from "@/hooks/useRunState"
import { RunActionButton } from "./RunActionButton"
import { StopResumeDropButtons } from "./StopResumeDropButtons"
import { UnblockDialog } from "./UnblockDialog"

interface Props {
  runId: string
  status: string | undefined
  debugMode: boolean
  elapsed: string
  selectedIssueId: string | null
  selectedIssue: IssueState | null
  onChange: () => void
}

export function RunHeader({
  runId,
  status,
  debugMode,
  elapsed,
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
    const r = await fetch(`/api/runs/${runId}/retry/${selectedIssueId}`, { method: "POST" })
    if (!r.ok) {
      const body = (await r.json().catch(() => ({}))) as { error?: string }
      toast.error(body.error ?? `HTTP ${r.status}`)
      return
    }
    toast.success("Retry requested")
    onChange()
  }

  const statusColor =
    status === "running"
      ? "text-foreground"
      : status === "completed"
        ? "text-emerald-500"
        : status === "stopped"
          ? "text-muted-foreground"
          : status === "errored"
            ? "text-destructive"
            : "text-muted-foreground"

  return (
    <header className="border-b border-border bg-background px-5 py-3 flex items-center gap-4">
      <Link to="/" className="text-[12px] text-muted-foreground hover:text-foreground flex items-center gap-1">
        <ArrowLeft size={14} />
        all runs
      </Link>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(runId)
          toast.success("Copied run id")
        }}
        className="font-mono text-sm font-semibold text-foreground hover:underline"
      >
        {runId}
      </button>
      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className={statusColor}>● {status ?? "unknown"}</span>
        {debugMode && <span className="text-[#d4a064]">debug</span>}
        {elapsed && <span className="tabular-nums">{elapsed}</span>}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <RunActionButton onClick={() => void retry()} disabled={!retryEnabled}>
          Retry
        </RunActionButton>
        <RunActionButton
          onClick={() => setUnblockOpen(true)}
          disabled={!unblockEnabled}
        >
          Unblock…
        </RunActionButton>
        <StopResumeDropButtons runId={runId} status={status} onChange={onChange} />
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
    </header>
  )
}
