import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { Plus, Pause, ChevronRight, Crosshair } from "lucide-react"

import { AppShell, AppHeader } from "@/components/ui/app-shell"
import { Button } from "@/components/ui/button"
import { StatusPill, type StatusKind } from "@/components/ui/status-pill"
import { EmptyState } from "@/components/ui/empty-state"
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

function runKind(run: RunSummary): StatusKind {
  if ((run.debug_reviews?.length ?? 0) > 0) return "attention"
  if (run.status === "running") return "running"
  if (run.status === "completed") return "completed"
  if (run.status === "stopped") return "stopped"
  if (run.status === "errored") return "errored"
  return "draft"
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
    <AppShell>
      <AppHeader
        breadcrumb={[{ label: "orca" }]}
        actions={
          <Button variant="primary" onClick={() => setNewRunOpen(true)}>
            <Plus size={14} />
            New run
          </Button>
        }
      />

      <div className="max-w-[1024px] mx-auto px-6 py-6">
        {error && (
          <div className="mb-4 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/5 text-[var(--danger)] px-4 py-2.5 text-[13px]">
            Could not reach daemon API: {error}
          </div>
        )}

        {/* Active debug-review pauses — most important thing on the page */}
        {allDebugReviews.length > 0 && (
          <section className="mb-6 rounded-md border-l-2 border-[var(--attention)] bg-[var(--surface)] border-y border-r border-[var(--border)]">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border)]">
              <Pause size={14} className="text-[var(--attention)]" />
              <h2 className="text-[12px] font-semibold uppercase tracking-wider text-[var(--attention)]">
                Awaiting your review
              </h2>
              <span className="text-[11px] text-[var(--fg-muted)] tabular-nums ml-1">
                {allDebugReviews.length}
              </span>
            </div>
            <ul>
              {allDebugReviews.map(({ run, review }, idx) => {
                let pathname = ""
                try {
                  pathname = new URL(review.url).pathname
                } catch {
                  pathname = `/debug/${run.run_id}/${review.issue_id}`
                }
                return (
                  <li
                    key={`${run.run_id}-${review.issue_id}`}
                    className={idx > 0 ? "border-t border-[var(--border-muted)]" : ""}
                  >
                    <Link
                      to={pathname}
                      className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--subtle)] transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-mono text-[13px] font-semibold text-[var(--accent-fg)] truncate">
                          {run.run_id}
                        </div>
                        <div className="text-[11.5px] text-[var(--fg-muted)] mt-0.5">
                          state{" "}
                          <span className="font-mono bg-[var(--subtle)] px-1.5 py-px rounded-sm text-[var(--fg)]">
                            {review.state}
                          </span>{" "}
                          · paused for review
                        </div>
                      </div>
                      <ChevronRight size={16} className="text-[var(--fg-subtle)] shrink-0" />
                    </Link>
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        <section>
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--fg-subtle)] mb-2.5">
            Runs
          </h2>
          {runs === null ? (
            <div className="text-[13px] text-[var(--fg-muted)] italic">Loading…</div>
          ) : runs.length === 0 ? (
            <EmptyState
              icon={<Crosshair size={24} />}
              title="No runs on this daemon yet"
              description={
                <>
                  Start your first orca run from this dashboard, or via{" "}
                  <code className="bg-[var(--subtle)] px-1 py-px rounded-sm font-mono text-[12px]">
                    orca flow run
                  </code>
                  .
                </>
              }
              action={
                <Button variant="primary" onClick={() => setNewRunOpen(true)}>
                  <Plus size={14} />
                  New run
                </Button>
              }
            />
          ) : (
            <ul className="rounded-md border border-[var(--border)] bg-[var(--surface)]">
              {runs.map((run, idx) => {
                const kind = runKind(run)
                const activeReviews = run.debug_reviews ?? []
                return (
                  <li
                    key={run.run_id}
                    className={idx > 0 ? "border-t border-[var(--border-muted)]" : ""}
                  >
                    <Link
                      to="/runs/$runId"
                      params={{ runId: run.run_id }}
                      className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--subtle)] transition-colors"
                    >
                      <StatusPill kind={kind} />
                      <span className="font-mono text-[13px] font-semibold text-[var(--accent-fg)] truncate">
                        {run.run_id}
                      </span>
                      <span className="text-[11.5px] text-[var(--fg-muted)] truncate">
                        {run.terminal_count}/{run.issue_count} done
                      </span>
                      {run.debug && (
                        <StatusPill kind="attention" label="debug" pulse={false} size="sm" />
                      )}
                      {activeReviews.length > 0 && (
                        <StatusPill
                          kind="attention"
                          label={`${activeReviews.length} awaiting review`}
                          size="sm"
                          className="ml-auto"
                        />
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>

      <NewRunDialog open={newRunOpen} onOpenChange={setNewRunOpen} />
    </AppShell>
  )
}
