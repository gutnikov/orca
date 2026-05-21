import type { Explanation } from "@/lib/explain"

export function ExplainHeader({ data }: { data: Explanation }) {
  const date = new Date(data.generated_at)
  const dateStr = isNaN(date.getTime()) ? data.generated_at : date.toLocaleString()
  return (
    <header className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[10px] font-semibold tracking-wider uppercase">
          {data.language}
        </span>
        <span className="text-xs text-muted-foreground font-mono">{data.flow}</span>
        <span className="ml-auto text-[11px] text-muted-foreground">Generated {dateStr}</span>
      </div>
      <h1 className="text-3xl font-semibold leading-tight">{data.title}</h1>
      <p className="text-base text-muted-foreground leading-relaxed">{data.summary}</p>
    </header>
  )
}
