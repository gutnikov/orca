import { useState } from "react"
import { CheckCircle2, ChevronDown, ChevronRight, MinusCircle, XCircle } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { Criterion } from "@/lib/schema"

const STATUS_STYLE: Record<Criterion["status"], { tint: string; icon: typeof CheckCircle2 }> = {
  passed: {
    tint: "bg-[oklch(0.92_0.05_150)] text-[oklch(0.35_0.15_150)] dark:bg-[oklch(0.25_0.08_150)] dark:text-[oklch(0.85_0.12_150)]",
    icon: CheckCircle2,
  },
  failed: {
    tint: "bg-[oklch(0.93_0.05_30)] text-[oklch(0.45_0.20_30)] dark:bg-[oklch(0.25_0.08_30)] dark:text-[oklch(0.85_0.14_30)]",
    icon: XCircle,
  },
  skipped: {
    tint: "bg-muted text-muted-foreground",
    icon: MinusCircle,
  },
}

function CriterionRow({ criterion }: { criterion: Criterion }) {
  const [open, setOpen] = useState(false)
  const { tint, icon: Icon } = STATUS_STYLE[criterion.status]
  const hasDetail = !!criterion.detail
  return (
    <div className="border-b last:border-b-0">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((o) => !o)}
        disabled={!hasDetail}
        className={cn(
          "w-full flex items-center gap-3 px-3 py-2 text-left",
          hasDetail && "hover:bg-muted/40 transition-colors",
        )}
      >
        <span className={cn("h-5 w-5 inline-flex items-center justify-center rounded-full", tint)}>
          <Icon size={12} />
        </span>
        <span className="font-mono text-xs font-semibold shrink-0">{criterion.name}</span>
        {criterion.summary ? (
          <span className="text-xs text-muted-foreground truncate flex-1">{criterion.summary}</span>
        ) : null}
        {hasDetail ? (
          <span className="text-muted-foreground shrink-0">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        ) : null}
      </button>
      {hasDetail && open ? (
        <div className="px-3 pb-3 pt-1 prose prose-sm dark:prose-invert max-w-none text-xs">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{criterion.detail!}</ReactMarkdown>
        </div>
      ) : null}
    </div>
  )
}

export default function AssertionsBlock({ criteria }: { criteria: Criterion[] }) {
  if (criteria.length === 0) {
    return (
      <Card className="p-4 text-sm text-muted-foreground text-center">
        No assertions to report.
      </Card>
    )
  }
  const passed = criteria.filter((c) => c.status === "passed").length
  const failed = criteria.filter((c) => c.status === "failed").length
  const skipped = criteria.filter((c) => c.status === "skipped").length
  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2 border-b bg-card/85 backdrop-blur-sm text-xs font-mono">
        <span className="text-[oklch(0.55_0.18_150)]">{passed} passed</span>
        <span className="text-[oklch(0.55_0.20_30)]">{failed} failed</span>
        {skipped > 0 ? <span className="text-muted-foreground">{skipped} skipped</span> : null}
      </div>
      <div>
        {criteria.map((c) => <CriterionRow key={c.name} criterion={c} />)}
      </div>
    </Card>
  )
}
