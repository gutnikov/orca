import type { WalkthroughStep } from "@/lib/explain"

export function WalkthroughList({ steps }: { steps: WalkthroughStep[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Walkthrough</h2>
      <ol className="space-y-3 relative pl-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-px before:bg-border">
        {steps.map((step, i) => (
          <li key={i} className="relative">
            <span className="absolute -left-[1.1rem] top-1 h-2.5 w-2.5 rounded-full bg-primary border-2 border-background" />
            <div className="text-xs font-mono text-muted-foreground">{step.state}</div>
            <div className="text-sm leading-relaxed">{step.what_happens}</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              <span className="font-semibold">Expected:</span> {step.expected_outcome}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
