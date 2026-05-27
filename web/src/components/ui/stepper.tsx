import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"

export type StepState = "done" | "running" | "pending" | "failed"

export interface Step {
  id: string
  state: StepState
  name: string
  outcome?: string
  duration?: string
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
            <div className="flex items-center gap-2 text-[12px]">
              <span className="font-mono text-[var(--fg)] truncate">{step.name}</span>
              {step.outcome && (
                <span className="font-mono text-[10.5px] text-[var(--fg-subtle)] bg-[var(--overlay)] px-1.5 py-px rounded-[var(--radius-pill)] truncate">
                  {step.outcome}
                </span>
              )}
              {step.duration && (
                <span className="ml-auto text-[10.5px] text-[var(--fg-subtle)] tabular-nums shrink-0">
                  {step.duration}
                </span>
              )}
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}
