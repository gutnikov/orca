import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { Pause, ChevronRight, Plus } from "lucide-react"
import { NewRunDialog } from "@/components/home/NewRunDialog"

interface DebugReview {
  issue_id: string
  state: string
  url: string
}

interface RunSummary {
  run_id: string
  branch: string
  workflow: string
  status: string
  issue_count: number
  terminal_count: number
  created_at: string
  waiting_issues?: Array<{ issue_id: string; state: string; reason: string }>
  debug_reviews?: DebugReview[]
  debug?: boolean
}

export const Route = createFileRoute("/")({
  component: HomePage,
})

function HomePage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [newRunOpen, setNewRunOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const res = await fetch("/api/runs")
        if (!res.ok) {
          if (!cancelled) setError(`HTTP ${res.status}`)
          return
        }
        const data: RunSummary[] = await res.json()
        if (!cancelled) {
          setRuns(data)
          setError(null)
        }
      } catch (exc) {
        if (!cancelled) setError(String(exc))
      }
    }
    void tick()
    const id = setInterval(() => void tick(), 3000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const allDebugReviews: Array<{ run: RunSummary; review: DebugReview }> = []
  for (const run of runs ?? []) {
    for (const review of run.debug_reviews ?? []) {
      allDebugReviews.push({ run, review })
    }
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="max-w-[1024px] mx-auto px-6 py-8 pr-32">
        <header className="mb-6 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">orca</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Active runs on this daemon.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setNewRunOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-[12px] font-medium hover:opacity-90"
          >
            <Plus size={14} />
            New run
          </button>
        </header>

        {error ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 text-destructive px-4 py-3 text-sm">
            Could not reach daemon API: {error}
          </div>
        ) : null}

        {/* Active debug-review pauses — most important thing on the page */}
        {allDebugReviews.length > 0 ? (
          <section className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <Pause size={16} className="text-[#d4a064]" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-[#d4a064]">
                Awaiting your review
              </h2>
              <span className="text-xs text-muted-foreground tabular-nums">
                {allDebugReviews.length}
              </span>
            </div>
            <ul className="space-y-2">
              {allDebugReviews.map(({ run, review }) => {
                // Extract path from the review URL so we can use TanStack Link
                let pathname = ""
                try {
                  pathname = new URL(review.url).pathname
                } catch {
                  pathname = `/debug/${run.run_id}/${review.issue_id}`
                }
                return (
                  <li key={`${run.run_id}-${review.issue_id}`}>
                    <Link
                      to={pathname}
                      className="block rounded-lg border-2 border-[#d4a064]/40 bg-[#d4a064]/5 hover:bg-[#d4a064]/10 hover:border-[#d4a064]/60 transition-colors px-4 py-3"
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="font-mono text-sm font-semibold truncate">
                            {run.run_id}
                          </div>
                          <div className="text-[12px] text-muted-foreground mt-0.5">
                            state{" "}
                            <span className="font-mono bg-muted px-1.5 py-0.5 rounded text-foreground">
                              {review.state}
                            </span>{" "}
                            · paused for review
                          </div>
                        </div>
                        <ChevronRight size={18} className="text-muted-foreground shrink-0" />
                      </div>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </section>
        ) : null}

        {/* All runs list */}
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Runs
          </h2>
          {runs === null ? (
            <div className="text-sm text-muted-foreground italic">Loading…</div>
          ) : runs.length === 0 ? (
            <div className="rounded-lg border border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground italic">
              No runs on this daemon yet. Start one with{" "}
              <code className="bg-muted px-1 py-0.5 rounded">orca flow run</code>.
            </div>
          ) : (
            <ul className="space-y-2">
              {runs.map((run) => {
                const activeReviews = run.debug_reviews ?? []
                return (
                  <li key={run.run_id}>
                    <div
                      className={
                        activeReviews.length > 0
                          ? "rounded-lg border-2 border-[#d4a064]/45 bg-[#d4a064]/5 px-4 py-3 flex items-center gap-3"
                          : "rounded-lg border border-border bg-card px-4 py-3 flex items-center gap-3"
                      }
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-mono text-sm font-semibold truncate">
                          {run.run_id}
                        </div>
                        <div className="text-[12px] text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                          <span>
                            status{" "}
                            <span
                              className={
                                run.status === "running"
                                  ? "text-foreground"
                                  : run.status === "completed"
                                    ? "text-[oklch(0.65_0.18_150)]"
                                    : "text-muted-foreground"
                              }
                            >
                              {run.status}
                            </span>
                          </span>
                          <span>
                            {run.terminal_count}/{run.issue_count} done
                          </span>
                          {run.debug ? (
                            <span className="text-[#d4a064]">debug mode</span>
                          ) : null}
                          {activeReviews.length > 0 ? (
                            <span className="inline-flex items-center gap-1.5 text-[#d4a064] font-semibold">
                              <Pause size={12} />
                              awaiting review
                            </span>
                          ) : null}
                        </div>
                        {activeReviews.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {activeReviews.map((review) => {
                              let pathname = ""
                              try {
                                pathname = new URL(review.url).pathname
                              } catch {
                                pathname = `/debug/${run.run_id}/${review.issue_id}`
                              }
                              return (
                                <Link
                                  key={review.issue_id}
                                  to={pathname}
                                  className="inline-flex items-center rounded-md border border-[#d4a064]/35 bg-[#d4a064]/10 px-2 py-0.5 text-[11px] font-mono text-[#d4a064] hover:bg-[#d4a064]/15"
                                >
                                  {review.issue_id} · {review.state}
                                </Link>
                              )
                            })}
                          </div>
                        ) : null}
                      </div>
                      <Link
                        to="/runs/$runId"
                        params={{ runId: run.run_id }}
                        className="text-xs underline opacity-70 hover:opacity-100 shrink-0"
                      >
                        view past reviews →
                      </Link>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
      <NewRunDialog open={newRunOpen} onOpenChange={setNewRunOpen} />
    </main>
  )
}
