import { useState } from "react"
import { Dialog } from "radix-ui"
import { toast } from "sonner"
import { useNavigate } from "@tanstack/react-router"
import { X, ChevronDown, ChevronRight } from "lucide-react"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function NewRunDialog({ open, onOpenChange }: Props) {
  const navigate = useNavigate()
  const [taskFile, setTaskFile] = useState("")
  const [workflow, setWorkflow] = useState("")
  const [debug, setDebug] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [maxHops, setMaxHops] = useState("")
  const [maxRetries, setMaxRetries] = useState("")
  const [workerOverrides, setWorkerOverrides] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const submit = async () => {
    setErrorMsg(null)
    if (!taskFile.trim()) {
      setErrorMsg("Task file is required.")
      return
    }
    const body: Record<string, unknown> = { task_file: taskFile.trim(), debug }
    if (workflow.trim()) body.workflow = workflow.trim()
    if (maxHops.trim()) body.max_hops = Number(maxHops)
    if (maxRetries.trim()) body.max_retries = Number(maxRetries)
    if (workerOverrides.trim()) {
      try {
        body.worker_overrides = JSON.parse(workerOverrides)
      } catch (exc) {
        setErrorMsg(`worker_overrides is not valid JSON: ${exc}`)
        return
      }
    }
    setSubmitting(true)
    try {
      const r = await fetch("/api/runs/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const errBody = (await r.json().catch(() => ({}))) as { error?: string }
        setErrorMsg(errBody.error ?? `HTTP ${r.status}`)
        return
      }
      const result = (await r.json()) as { run_id: string }
      toast.success(`Started ${result.run_id}`)
      onOpenChange(false)
      void navigate({ to: "/runs/$runId", params: { runId: result.run_id } })
    } catch (exc) {
      setErrorMsg(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[520px] max-w-[92vw] rounded-lg border border-border bg-card p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <Dialog.Title className="text-sm font-semibold">New run</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="text-muted-foreground hover:text-foreground">
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>
          <div className="space-y-3">
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Task file</span>
              <input
                type="text"
                value={taskFile}
                onChange={(e) => setTaskFile(e.target.value)}
                placeholder="e.g. tasks/DEV-52.json"
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[13px]"
                autoFocus
              />
            </label>
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Workflow (optional)</span>
              <input
                type="text"
                value={workflow}
                onChange={(e) => setWorkflow(e.target.value)}
                placeholder="defaults to repo's primary workflow"
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[13px]"
              />
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={debug}
                onChange={(e) => setDebug(e.target.checked)}
                className="accent-primary"
              />
              <span>Debug mode</span>
              <span className="text-[11px] text-muted-foreground">(pause for review at each state)</span>
            </label>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
            >
              {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              Advanced
            </button>
            {showAdvanced && (
              <div className="space-y-3 pl-4 border-l border-border">
                <label className="block">
                  <span className="text-[11px] text-muted-foreground">max_hops</span>
                  <input
                    type="number"
                    value={maxHops}
                    onChange={(e) => setMaxHops(e.target.value)}
                    className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[13px]"
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] text-muted-foreground">max_retries</span>
                  <input
                    type="number"
                    value={maxRetries}
                    onChange={(e) => setMaxRetries(e.target.value)}
                    className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[13px]"
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] text-muted-foreground">worker_overrides (JSON)</span>
                  <textarea
                    value={workerOverrides}
                    onChange={(e) => setWorkerOverrides(e.target.value)}
                    placeholder='{"planning": {"effort": "high"}}'
                    className="mt-1 w-full min-h-[80px] rounded-md border border-border bg-background px-2 py-1.5 text-[13px] font-mono resize-y"
                  />
                </label>
              </div>
            )}
            {errorMsg && (
              <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
                {errorMsg}
              </div>
            )}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close asChild>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-[12px] hover:bg-muted"
              >
                Cancel
              </button>
            </Dialog.Close>
            <button
              type="button"
              onClick={submit}
              disabled={submitting}
              className="rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-[12px] font-medium disabled:opacity-40"
            >
              {submitting ? "Starting…" : "Start run"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
