import type { Explanation } from "@/lib/explain"

export function ExplainPage({ data }: { data: Explanation }) {
  return (
    <main className="max-w-5xl mx-auto p-6 space-y-4">
      <h1 className="text-3xl font-semibold">{data.title}</h1>
      <p className="text-muted-foreground">{data.summary}</p>
      <pre className="text-xs font-mono bg-muted/40 p-3 rounded-md overflow-x-auto">
        {JSON.stringify(data, null, 2)}
      </pre>
    </main>
  )
}
