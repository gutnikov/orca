import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

interface Attempt {
  attempt: number;
  state: string;
  state_local_index: number;
  paused_at: string;
  decision: string | null;
  decided_at: string | null;
}

interface IssueValue {
  state: string;
  fields?: { title?: string };
}

interface RunDetail {
  run_id: string;
  status?: string;
  state: { issues: Record<string, IssueValue> };
}

function groupByState(attempts: Attempt[]): Map<string, Attempt[]> {
  const m = new Map<string, Attempt[]>();
  for (const a of attempts) {
    const key = a.state ?? "?";
    const arr = m.get(key) ?? [];
    arr.push(a);
    m.set(key, arr);
  }
  return m;
}

function AttemptsForIssue({ runId, issueId }: { runId: string; issueId: string }) {
  const [attempts, setAttempts] = useState<Attempt[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const r = await fetch(`/api/runs/${runId}/issues/${issueId}/debug/attempts`);
      if (r.ok && !cancelled) setAttempts(await r.json());
    })();
    return () => { cancelled = true; };
  }, [runId, issueId]);

  if (attempts === null) return <span className="text-xs opacity-50">loading…</span>;
  if (attempts.length === 0) return <span className="text-xs opacity-50">no reviews</span>;
  const grouped = groupByState(attempts);
  return (
    <div className="flex flex-col gap-1 text-sm">
      {Array.from(grouped.entries()).map(([state, group]) => (
        <div key={state} className="flex gap-2 items-center">
          <span className="font-medium">{state}</span>
          {group.map((a) => (
            <Link
              key={a.attempt}
              to="/debug/$runId/$issueId"
              params={{ runId, issueId }}
              search={{ attempt: a.attempt }}
              className="text-xs underline opacity-70 hover:opacity-100"
            >
              v{a.state_local_index}{a.decision === null ? " (undecided)" : ""}
            </Link>
          ))}
        </div>
      ))}
    </div>
  );
}

function RunDetailPage() {
  const { runId } = Route.useParams();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const decoded = decodeURIComponent(runId);
    let cancelled = false;
    void (async () => {
      try {
        const r = await fetch(`/api/runs/${decoded}`);
        if (cancelled) return;
        if (!r.ok) { setError(`HTTP ${r.status}`); return; }
        const data: RunDetail = await r.json();
        if (cancelled) return;
        setRun(data);
      } catch (exc) {
        if (cancelled) return;
        setError(String(exc));
      }
    })();
    return () => { cancelled = true; };
  }, [runId]);

  if (error) return <div className="p-8 text-red-500">{error}</div>;
  if (!run) return <div className="p-8 opacity-50">Loading…</div>;
  const decoded = decodeURIComponent(runId);

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="max-w-[1024px] mx-auto px-6 py-8">
        <Link to="/" className="text-xs underline opacity-70">← all runs</Link>
        <h1 className="text-xl font-semibold tracking-tight mt-2">{run.run_id}</h1>
        <div className="text-sm text-muted-foreground mb-6">status: {run.status ?? "unknown"}</div>
        <div className="flex flex-col gap-4">
          {Object.entries(run.state.issues).map(([issueId, issue]) => (
            <div key={issueId} className="border rounded p-3">
              <div className="text-sm font-medium">
                {issueId} <span className="opacity-50">— {issue.state}</span>
              </div>
              <AttemptsForIssue runId={decoded} issueId={issueId} />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

export const Route = createFileRoute("/runs/$runId")({
  component: RunDetailPage,
});
