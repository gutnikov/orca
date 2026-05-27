import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { AppShell, AppHeader } from "@/components/ui/app-shell";
import { DebugReviewLayout, type PastReview } from "../components/review/DebugReviewLayout";
import { PostDecisionScreen } from "../components/review/PostDecisionScreen";
import type { DebugAction } from "../components/review/ActionButton";

interface Snapshot {
  rendered_prompt: string;
  worker_result: Record<string, unknown>;
  config_slice: string;
  diff_files: Array<{ path: string; status: string; hunks: unknown[] }>;
  base_commit: string;
  past_review?: PastReview;
}

function DebugReviewPage() {
  const { runId, issueId } = Route.useParams();
  const { attempt } = Route.useSearch();
  const readOnly = attempt !== undefined;

  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submittedAction, setSubmittedAction] = useState<DebugAction | null>(null);
  const [stateName, setStateName] = useState<string>("");

  useEffect(() => {
    const decoded = decodeURIComponent(runId);
    void (async () => {
      try {
        const debugUrl =
          attempt !== undefined
            ? `/api/runs/${decoded}/issues/${issueId}/debug?attempt=${attempt}`
            : `/api/runs/${decoded}/issues/${issueId}/debug`;

        const [snapRes, issueRes] = await Promise.all([
          fetch(debugUrl),
          fetch(`/api/runs/${decoded}/issues/${issueId}`),
        ]);
        if (snapRes.status === 404) {
          setError(
            readOnly
              ? "This past review was not found."
              : "This issue is not currently paused for debug review.",
          );
          return;
        }
        if (!snapRes.ok) {
          setError(`Failed to fetch debug review: HTTP ${snapRes.status}`);
          return;
        }
        const snap: Snapshot = await snapRes.json();
        setSnapshot(snap);
        if (issueRes.ok) {
          const issue = await issueRes.json();
          setStateName(issue.state ?? "");
        }
      } catch (exc) {
        setError(String(exc));
      }
    })();
  }, [runId, issueId, attempt]);

  const handleSubmit = async (action: DebugAction) => {
    // In read-only (past review) mode, submissions are blocked defensively —
    // the action bar is hidden anyway, so this should never be called.
    if (readOnly) return;

    const decoded = decodeURIComponent(runId);
    // Comments are NOT sent on the wire — the daemon persists them as the
    // user authors them (Task 7) and the reducer bundles them into the
    // debug_modify_request payload from the persisted state at decision time.
    const res = await fetch(`/api/runs/${decoded}/issues/${issueId}/debug/decide`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (res.ok || res.status === 409) {
      setSubmittedAction(action);
    } else {
      const body = await res.json().catch(() => ({}));
      setError(body.error ?? `HTTP ${res.status}`);
    }
  };

  if (error) {
    return (
      <AppShell>
        <AppHeader breadcrumb={[{ label: "orca", to: "/" }]} />
        <div className="flex items-center justify-center p-8 text-center" style={{ minHeight: "calc(100vh - 3rem)" }}>
          <div>
            <div className="text-[var(--danger)] text-3xl">⚠</div>
            <h2 className="text-xl font-semibold mt-2">{error}</h2>
          </div>
        </div>
      </AppShell>
    );
  }
  if (submittedAction) {
    return (
      <AppShell>
        <AppHeader
          breadcrumb={[
            { label: "orca", to: "/" },
            { label: "runs", to: "/" },
            { label: runId, mono: true, to: "/runs/$runId", params: { runId } },
            { label: `debug · ${issueId.slice(0, 8)}`, mono: true },
          ]}
        />
        <PostDecisionScreen
          runId={decodeURIComponent(runId)}
          issueId={issueId}
          state={stateName}
          action={submittedAction}
        />
      </AppShell>
    );
  }
  if (!snapshot) {
    return (
      <AppShell>
        <AppHeader
          breadcrumb={[
            { label: "orca", to: "/" },
            { label: "runs", to: "/" },
            { label: runId, mono: true, to: "/runs/$runId", params: { runId } },
            { label: `debug · ${issueId.slice(0, 8)}`, mono: true },
          ]}
        />
        <div className="p-8 opacity-50">Loading debug review…</div>
      </AppShell>
    );
  }
  return (
    <AppShell>
      <AppHeader
        breadcrumb={[
          { label: "orca", to: "/" },
          { label: "runs", to: "/" },
          { label: runId, mono: true, to: "/runs/$runId", params: { runId } },
          { label: `debug · ${issueId.slice(0, 8)}`, mono: true },
        ]}
      />
      <DebugReviewLayout
        runId={decodeURIComponent(runId)}
        issueId={issueId}
        state={readOnly && snapshot.past_review ? snapshot.past_review.state : stateName}
        snapshot={snapshot}
        onSubmit={handleSubmit}
        readOnly={readOnly}
        pastReview={snapshot.past_review ?? null}
      />
    </AppShell>
  );
}

export const Route = createFileRoute("/debug/$runId/$issueId")({
  component: DebugReviewPage,
  validateSearch: (search: Record<string, unknown>): { attempt?: number } => {
    const a = search.attempt;
    if (a === undefined || a === null || a === "") return {};
    const n = typeof a === "number" ? a : parseInt(String(a), 10);
    return Number.isFinite(n) && n >= 0 ? { attempt: n } : {};
  },
});
