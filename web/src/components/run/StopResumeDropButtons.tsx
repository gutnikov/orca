import { useState } from "react"
import { toast } from "sonner"
import { useNavigate } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"

interface Props {
  runId: string
  status: string | undefined
  onChange: () => void
}

export function StopResumeDropButtons({ runId, status, onChange }: Props) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState<"stop" | "resume" | "drop" | null>(null)

  const post = async (path: string, label: "stop" | "resume" | "drop") => {
    setBusy(label)
    try {
      const r = await fetch(`/api/runs/${runId}/${path}`, { method: "POST" })
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { error?: string }
        toast.error(body.error ?? `HTTP ${r.status}`)
        return
      }
      toast.success(`${label} ok`)
      onChange()
      if (label === "drop") {
        void navigate({ to: "/" })
      }
    } finally {
      setBusy(null)
    }
  }

  const isRunning = status === "running"
  const isStopped = status === "stopped"

  return (
    <>
      {isRunning && (
        <Button size="sm" onClick={() => void post("stop", "stop")} disabled={busy !== null}>
          {busy === "stop" ? "Stopping…" : "Stop"}
        </Button>
      )}
      {isStopped && (
        <Button size="sm" onClick={() => void post("resume", "resume")} disabled={busy !== null}>
          {busy === "resume" ? "Resuming…" : "Resume"}
        </Button>
      )}
      <Button
        size="sm"
        variant="danger"
        onClick={() => {
          if (window.confirm("Drop this run? This cannot be undone.")) {
            void post("drop", "drop")
          }
        }}
        disabled={busy !== null}
      >
        {busy === "drop" ? "Dropping…" : "Drop"}
      </Button>
    </>
  )
}
