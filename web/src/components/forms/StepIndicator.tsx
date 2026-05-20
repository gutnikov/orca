import type { FormStep } from "@/lib/schema"

export function StepIndicator({ steps, current }: { steps: FormStep[]; current: number }) {
  if (steps.length <= 1) return null
  return (
    <div className="flex items-center gap-2 mb-6">
      <div className="flex items-center gap-1">
        {steps.map((_, i) => (
          <div key={i} className="flex items-center gap-1">
            <div
              className={`h-2 w-2 rounded-full transition-colors ${
                i <= current ? "bg-primary" : "bg-muted"
              }`}
              aria-hidden
            />
            {i < steps.length - 1 ? (
              <div
                className={`h-px w-6 transition-colors ${
                  i < current ? "bg-primary" : "bg-muted"
                }`}
                aria-hidden
              />
            ) : null}
          </div>
        ))}
      </div>
      <span className="text-xs text-muted-foreground ml-3">
        Step {current + 1} of {steps.length}
        {steps[current].title ? ` — ${steps[current].title}` : ""}
      </span>
    </div>
  )
}
