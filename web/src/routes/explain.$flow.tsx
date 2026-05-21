import { createFileRoute, notFound } from "@tanstack/react-router"
import { z } from "zod"
import { loadExplanation, ExplanationNotFoundError, ExplanationCorruptedError } from "@/lib/explain"
import { ExplainPage } from "@/components/explain/ExplainPage"

const searchSchema = z.object({
  lang: z.string().default("en"),
})

export const Route = createFileRoute("/explain/$flow")({
  validateSearch: searchSchema,
  loaderDeps: ({ search }) => ({ lang: search.lang }),
  loader: async ({ params, deps }) => {
    try {
      return await loadExplanation(params.flow, deps.lang)
    } catch (e) {
      if (e instanceof ExplanationNotFoundError) {
        throw notFound({ data: { hint: e.hint, flow: params.flow, lang: deps.lang } })
      }
      throw e
    }
  },
  component: ExplainRoute,
  notFoundComponent: ({ data }) => {
    const { hint, flow, lang } = (data ?? {}) as { hint?: string; flow?: string; lang?: string }
    return (
      <main className="max-w-2xl mx-auto p-8 mt-12 text-center space-y-4">
        <h1 className="text-xl font-semibold">No explanation yet</h1>
        <p className="text-muted-foreground text-sm">
          {hint ?? `No explanation cached for flow '${flow}' (${lang}).`}
        </p>
        <pre className="inline-block text-left text-xs font-mono bg-muted/40 px-3 py-2 rounded-md">
          orca-workflow-explain {flow ?? "<flow>"} --lang {lang ?? "en"}
        </pre>
      </main>
    )
  },
  errorComponent: ({ error }) => {
    if (error instanceof ExplanationCorruptedError) {
      return (
        <main className="max-w-2xl mx-auto p-8 mt-12 text-center">
          <h1 className="text-xl font-semibold">Explanation file is corrupted</h1>
          <p className="text-muted-foreground text-sm mt-2">{error.detail}</p>
          <p className="text-muted-foreground text-sm mt-2">Regenerate it via the orca-workflow-explain playbook.</p>
        </main>
      )
    }
    return (
      <main className="max-w-2xl mx-auto p-8 mt-12 text-center">
        <h1 className="text-xl font-semibold">Something went wrong</h1>
        <p className="text-muted-foreground text-sm mt-2">{String(error)}</p>
      </main>
    )
  },
})

function ExplainRoute() {
  const data = Route.useLoaderData()
  return <ExplainPage data={data} />
}
