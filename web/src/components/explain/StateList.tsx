import type { ExplainState } from "@/lib/explain"
import { StateCard } from "./StateCard"

export function StateList({ states }: { states: ExplainState[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">States</h2>
      <div className="space-y-3">
        {states.map((s) => <StateCard key={s.name} state={s} />)}
      </div>
    </section>
  )
}
