import { useCallback, useEffect, useState } from "react";

export interface InlineComment {
  file: string;
  line: number | null;
  body: string;
}

const DRAFT_KEY = (runId: string, issueId: string) =>
  `orca:debug:draft:${runId}:${issueId}`;

export function useDraftComments(runId: string, issueId: string) {
  const [comments, setComments] = useState<InlineComment[]>([]);

  useEffect(() => {
    const raw = localStorage.getItem(DRAFT_KEY(runId, issueId));
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setComments(parsed);
      } catch {
        // ignore corrupt drafts
      }
    }
  }, [runId, issueId]);

  useEffect(() => {
    localStorage.setItem(DRAFT_KEY(runId, issueId), JSON.stringify(comments));
  }, [runId, issueId, comments]);

  const add = useCallback((c: InlineComment) => {
    setComments((prev) => [...prev, c]);
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
