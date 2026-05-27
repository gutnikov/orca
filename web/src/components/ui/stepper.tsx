import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"

export type StepState = "done" | "running" | "pending" | "failed"

export interface Step {
  id: string
  state: StepState
  name: string
  outcome?: string
  duration?: string
  usage?: string | null
  progress?: number | null
  progressText?: string | null
  active?: boolean
  onClick?: () => void
}

interface Props {
  steps: Step[]
  className?: string
}

function StepIcon({ state }: { state: StepState }) {
  switch (state) {
    case "done":
      return <CheckCircle2 size={14} className="text-[var(--success-fg)]" />
    case "running":
      return <Loader2 size={14} className="animate-spin text-[var(--accent-fg)]" />
    case "failed":
      return <XCircle size={14} className="text-[var(--danger)]" />
    case "pending":
      return <Circle size={14} className="text-[var(--fg-subtle)]" />
  }
}

export function Stepper({ steps, className }: Props) {
  if (steps.length === 0) return null
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      {steps.map((step) => (
        <button
          type="button"
          key={step.id}
          onClick={step.onClick}
          className={cn(
            "w-full text-left flex items-start gap-2 px-2 py-1.5 rounded-md",
            "border-l-2 transition-colors duration-[120ms]",
            step.active
              ? "border-[var(--accent)] bg-[var(--accent-soft)]"
              : "border-transparent hover:bg-[var(--subtle)]",
          )}
        >
          <span className="mt-[2px] shrink-0">
            <StepIcon state={step.state} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-[12px] min-w-0">
              <span className="font-mono text-[var(--fg)] truncate shrink-0 max-w-[8rem]">
                {step.name}
              </span>
              {step.outcome && (
                <span className="font-mono text-[10.5px] text-[var(--fg-subtle)] bg-[var(--overlay)] px-1.5 py-px rounded-[var(--radius-pill)] truncate min-w-0">
                  {step.outcome}
                </span>
              )}
            </div>
            {(step.usage || step.duration) && (
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-[var(--fg-subtle)] tabular-nums">
                {step.usage && <span>{step.usage}</span>}
                {step.duration && <span>{step.duration}</span>}
              </div>
            )}
            {step.state === "running" && step.progress != null && step.progress > 0 && (
              <div className="mt-1 flex items-center gap-2">
                <div className="flex-1 h-[3px] rounded-full bg-[var(--overlay)] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[var(--accent-fg)] transition-[width] duration-500"
                    style={{ width: `${Math.min(step.progress, 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-[var(--fg-subtle)] tabular-nums shrink-0">
                  {step.progress}%
                </span>
              </div>
            )}
            {step.state === "running" && step.progressText && (
              <div className="mt-0.5 text-[10px] text-[var(--fg-muted)] truncate">
                {step.progressText}
              </div>
            )}
          </div>
        </button>
      ))}
    </div>
  )
}
