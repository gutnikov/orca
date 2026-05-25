import { useCallback, useEffect, useRef, useState } from "react";

export interface InlineComment {
  id: string;
  file: string;
  line: number | null;
  body: string;
}

const DRAFT_KEY = (runId: string, issueId: string) =>
  `orca:debug:draft:${runId}:${issueId}`;

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `c-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

async function putComment(runId: string, issueId: string, c: InlineComment): Promise<void> {
  try {
    await fetch(`/api/runs/${runId}/issues/${issueId}/comments/${c.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: c.file, line: c.line, body: c.body }),
    });
  } catch {
    // best-effort — localStorage remains the offline cache
  }
}

async function deleteComment(runId: string, issueId: string, commentId: string): Promise<void> {
  try {
    await fetch(`/api/runs/${runId}/issues/${issueId}/comments/${commentId}`, {
      method: "DELETE",
    });
  } catch {
    // best-effort
  }
}

interface ServerComment {
  id: string;
  file: string;
  line: number | null;
  body: string;
}

async function hydrateFromServer(runId: string, issueId: string): Promise<InlineComment[] | null> {
  try {
    const res = await fetch(`/api/runs/${runId}/issues/${issueId}/comments`);
    if (!res.ok) return null;
    const data: { comments: ServerComment[] } = await res.json();
    return data.comments.map((c) => ({
      id: c.id,
      file: c.file,
      line: c.line,
      body: c.body,
    }));
  } catch {
    return null;
  }
}

export function useDraftComments(runId: string, issueId: string) {
  const [comments, setComments] = useState<InlineComment[]>([]);
  const hydratedRef = useRef(false);

  // Hydrate from daemon on mount (daemon is source of truth post-0.7.0).
  // Falls back to localStorage if the daemon is unreachable.
  useEffect(() => {
    (async () => {
      const serverComments = await hydrateFromServer(runId, issueId);
      if (serverComments !== null) {
        setComments(serverComments);
        hydratedRef.current = true;
        return;
      }
      const raw = localStorage.getItem(DRAFT_KEY(runId, issueId));
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            // Back-compat: drafts saved before the id field shipped
            // get a generated id so question/thread correlation works
            setComments(parsed.map((c: Partial<InlineComment>) => ({
              id: c.id ?? newId(),
              file: c.file ?? "",
              line: c.line ?? null,
              body: c.body ?? "",
            })));
          }
        } catch {
          // ignore corrupt drafts
        }
      }
      hydratedRef.current = true;
    })();
  }, [runId, issueId]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    localStorage.setItem(DRAFT_KEY(runId, issueId), JSON.stringify(comments));
  }, [runId, issueId, comments]);

  const add = useCallback((c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => {
    const finalized: InlineComment = {
      id: c.id ?? newId(),
      file: c.file,
      line: c.line,
      body: c.body,
    };
    setComments((prev) => [...prev, finalized]);
    void putComment(runId, issueId, finalized);
  }, [runId, issueId]);

  const remove = useCallback((idx: number) => {
    setComments((prev) => {
      const target = prev[idx];
      if (target !== undefined) {
        void deleteComment(runId, issueId, target.id);
      }
      return prev.filter((_, i) => i !== idx);
    });
  }, [runId, issueId]);

  const update = useCallback((idx: number, body: string) => {
    setComments((prev) => prev.map((c, i) => {
      if (i !== idx) return c;
      const updated = { ...c, body };
      void putComment(runId, issueId, updated);
      return updated;
    }));
  }, [runId, issueId]);

  const clear = useCallback(() => {
    localStorage.removeItem(DRAFT_KEY(runId, issueId));
    setComments([]);
  }, [runId, issueId]);

  return { comments, add, remove, update, clear };
}
