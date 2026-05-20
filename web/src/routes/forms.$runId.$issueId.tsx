import { createFileRoute, notFound } from "@tanstack/react-router"
import { loadForm, FormNotFoundError, FormExpiredError } from "@/lib/api"
import { FormPage } from "@/components/forms/FormPage"
import { TerminalState } from "@/components/forms/TerminalState"

export const Route = createFileRoute("/forms/$runId/$issueId")({
  loader: async ({ params }) => {
    try {
      return await loadForm(params.runId, params.issueId)
    } catch (e) {
      if (e instanceof FormNotFoundError) throw notFound()
      throw e
    }
  },
  component: FormRouteComponent,
  errorComponent: ({ error }) => {
    if (error instanceof FormExpiredError) return <TerminalState variant="expired" />
    return (
      <main className="max-w-lg mx-auto p-8 mt-12 text-center">
        <h1 className="text-xl font-semibold">Something went wrong</h1>
        <p className="text-muted-foreground mt-2 text-sm">{String(error)}</p>
      </main>
    )
  },
  notFoundComponent: () => <TerminalState variant="not_found" />,
})

function FormRouteComponent() {
  const data = Route.useLoaderData()
  if ("alreadySubmitted" in data) {
    return <TerminalState variant="already_submitted" />
  }
  return <FormPage data={data} />
}
