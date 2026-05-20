import { createFileRoute, Link } from "@tanstack/react-router"
import { listPending } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"

export const Route = createFileRoute("/inbox")({
  loader: () => listPending(),
  component: InboxPage,
})

function InboxPage() {
  const pending = Route.useLoaderData()
  return (
    <main className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-semibold tracking-tight mb-6">Pending forms</h1>
      {pending.length === 0 ? (
        <p className="text-muted-foreground text-sm">No forms are waiting for input.</p>
      ) : (
        <div className="space-y-3">
          {pending.map((p) => (
            <Card key={`${p.run_id}/${p.issue_id}`}>
              <CardContent className="pt-6 flex justify-between items-center">
                <div>
                  <Link
                    to="/forms/$runId/$issueId"
                    params={{ runId: p.run_id, issueId: p.issue_id }}
                    className="font-medium hover:underline"
                  >
                    {p.title}
                  </Link>
                  <div className="text-xs text-muted-foreground mt-1">
                    {p.run_id} · {p.state} · since {p.started_waiting_at}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </main>
  )
}
