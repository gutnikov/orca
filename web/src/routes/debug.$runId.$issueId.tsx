import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { DebugReviewLayout } from "../components/review/DebugReviewLayout";
import { PostDecisionScreen } from "../components/review/PostDecisionScreen";
import type { DebugAction } from "../components/review/ActionButton";

interface Snapshot {
  rendered_prompt: string;
  worker_result: Record<string, unknown>;
  config_slice: string;
  diff_files: Array<{ path: string; status: string; hunks: unknown[] }>;
  base_commit: string;
}

function DebugReviewPage() {
  const { runId, issueId } = Route.useParams();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submittedAction, setSubmittedAction] = useState<DebugAction | null>(null);
  const [stateName, setStateName] = useState<string>("");

  useEffect(() => {
    const decoded = decodeURIComponent(runId);
    void (async () => {
      try {
        const [snapRes, issueRes] = await Promise.all([
          fetch(`/api/runs/${decoded}/issues/${issueId}/debug`),
          fetch(`/api/runs/${decoded}/issues/${issueId}`),
        ]);
        if (snapRes.status === 404) {
          setError("This issue is not currently paused for debug review.");
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
  }, [runId, issueId]);

  const handleSubmit = async (action: DebugAction) => {
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
      <div className="min-h-screen flex items-center justify-center p-8 text-center">
        <div>
          <div className="text-red-500 text-3xl">⚠</div>
          <h2 className="text-xl font-semibold mt-2">{error}</h2>
        </div>
      </div>
    );
  }
  if (submittedAction) {
    return (
      <PostDecisionScreen
        runId={decodeURIComponent(runId)}
        issueId={issueId}
        state={stateName}
        action={submittedAction}
      />
    );
  }
  if (!snapshot) {
    return <div className="p-8 opacity-50">Loading debug review…</div>;
  }
  return (
    <DebugReviewLayout
      runId={decodeURIComponent(runId)}
      issueId={issueId}
      state={stateName}
      snapshot={snapshot}
      onSubmit={handleSubmit}
    />
  );
}

export const Route = createFileRoute("/debug/$runId/$issueId")({
  component: DebugReviewPage,
});
