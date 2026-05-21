import { ChevronDown, ChevronRight } from "lucide-react"
import { useState } from "react"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { ExplainState } from "@/lib/explain"

export function StateCard({ state }: { state: ExplainState }) {
  const [open, setOpen] = useState(true)
  return (
    <Card className="p-0 gap-0 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-card/85 backdrop-blur-sm border-b text-left"
      >
        <span className="text-muted-foreground">
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </span>
        <span className="font-mono text-sm font-semibold">{state.name}</span>
        {state.is_passive ? (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            passive
          </span>
        ) : state.worker_kind ? (
          <span className="rounded bg-[oklch(0.92_0.05_260)] dark:bg-[oklch(0.25_0.08_260)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[oklch(0.40_0.18_260)] dark:text-[oklch(0.85_0.12_260)]">
            {state.worker_kind}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {state.transitions.length} transition{state.transitions.length === 1 ? "" : "s"}
        </span>
      </button>
      {open ? (
        <div className="p-4 space-y-4 text-sm">
          <p className="text-base">{state.one_line}</p>
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">What the prompt asks</div>
            <p className="text-muted-foreground leading-relaxed">{state.what_the_prompt_asks}</p>
          </div>
          {(state.inputs.length > 0 || state.outputs.length > 0) ? (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Inputs</div>
                <ul className="text-xs font-mono space-y-0.5">
                  {state.inputs.map((i) => <li key={i}>{i}</li>)}
                </ul>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Outputs</div>
                <ul className="text-xs font-mono space-y-0.5">
                  {state.outputs.map((o) => <li key={o}>{o}</li>)}
                </ul>
              </div>
            </div>
          ) : null}
          {state.transitions.length > 0 ? (
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Transitions</div>
              <ul className="space-y-1.5">
                {state.transitions.map((t, i) => (
                  <li key={i} className="flex items-baseline gap-2">
                    <span className="font-mono text-xs rounded bg-muted/50 px-1.5 py-0.5">{t.on}</span>
                    <span className="text-muted-foreground text-xs">→</span>
                    <span className="font-mono text-xs font-semibold">{t.to}</span>
                    <span className={cn("text-xs text-muted-foreground")}>· {t.explain}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
