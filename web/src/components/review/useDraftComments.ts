import { useCallback, useEffect, useState } from "react";

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

export function useDraftComments(runId: string, issueId: string) {
  const [comments, setComments] = useState<InlineComment[]>([]);

  useEffect(() => {
    const raw = localStorage.getItem(DRAFT_KEY(runId, issueId));
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          // Back-compat: drafts saved before the `id` field shipped
          // hydrate with generated ids so question correlation works on
          // any comment that was already in localStorage.
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
  }, [runId, issueId]);

  useEffect(() => {
    localStorage.setItem(DRAFT_KEY(runId, issueId), JSON.stringify(comments));
  }, [runId, issueId, comments]);

  const add = useCallback((c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => {
    setComments((prev) => [...prev, { id: c.id ?? newId(), file: c.file, line: c.line, body: c.body }]);
  }, []);

  const remove = useCallback((idx: number) => {
    setComments((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const update = useCallback((idx: number, body: string) => {
    setComments((prev) => prev.map((c, i) => (i === idx ? { ...c, body } : c)));
  }, []);

  const clear = useCallback(() => {
    localStorage.removeItem(DRAFT_KEY(runId, issueId));
    setComments([]);
  }, [runId, issueId]);

  return { comments, add, remove, update, clear };
}
