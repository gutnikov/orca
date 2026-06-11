import { useState } from "react"
import { Dialog } from "radix-ui"
import { toast } from "sonner"
import { X } from "lucide-react"

interface Props {
  runId: string
  issueId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSent: () => void
}

export function UnblockDialog({ runId, issueId, open, onOpenChange, onSent }: Props) {
  const [message, setMessage] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const submit = async () => {
    if (!message.trim()) return
    setSubmitting(true)
    try {
      const r = await fetch(`/api/runs/${runId}/unblock/${issueId}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message }),
      })
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { error?: string }
        toast.error(body.error ?? `HTTP ${r.status}`)
        return
      }
      toast.success("Unblock message sent")
      setMessage("")
      onOpenChange(false)
      onSent()
    } catch (exc) {
      toast.error(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[480px] max-w-[90vw] rounded-lg border border-border bg-card p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <Dialog.Title className="text-sm font-semibold">
              Unblock worker
            </Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="text-muted-foreground hover:text-foreground">
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="text-[12px] text-muted-foreground mb-3">
            Send a message to the worker. Useful when the worker is stuck waiting on input.
          </Dialog.Description>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="e.g. 'Use the pytest -x flag and only run the failing test'"
            className="w-full min-h-[120px] rounded-md border border-border bg-background p-2 text-[13px] resize-y"
            autoFocus
          />
          <div className="mt-4 flex justify-end gap-2">
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
              disabled={submitting || !message.trim()}
              className="rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-[12px] font-medium disabled:opacity-40"
            >
              {submitting ? "Sending…" : "Send"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
