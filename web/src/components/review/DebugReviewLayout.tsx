import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronsDownUp, ChevronsUpDown, MessageSquare } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";

/** Reserved file key for free-form feedback not anchored to any specific file. */
const OVERALL_FEEDBACK_FILE = "__overall__";

const overallFeedbackKey = (runId: string, issueId: string) =>
  `orca:debug:overall:${runId}:${issueId}`;

import { ActionButton, type DebugAction } from "./ActionButton";
import { type DiffViewOverlay } from "./DiffView";
import { DiffFileCard } from "./DiffFileCard";
import { FileTreeSidebar } from "./FileTreeSidebar";
import { VirtualFileCard } from "./VirtualFileCard";
import { useCommentThreads, type ThreadView } from "./useCommentThreads";
import { useDraftComments, type InlineComment } from "./useDraftComments";
import type { ChangesetFile, FileStatus, ReviewComment } from "./types";

function anchorForId(id: string): string {
  // Make any id safe for use as an HTML id (no spaces, slashes, etc.)
  return "file-" + id.replace(/[^a-zA-Z0-9_-]+/g, "-");
}

// Raw snapshot shape coming from the server (JSON, untyped hunks)
export interface DebugReviewSnapshot {
  rendered_prompt: string;
  worker_result: Record<string, unknown>;
  config_slice: string;
  diff_files: Array<{
    path: string;
    status: string;
    // The diff field carries the raw unified diff text when available.
    // If absent, hunks may be present as pre-parsed objects — ignored for now.
    diff?: string;
    language?: string;
    old_path?: string;
    additions?: number;
    deletions?: number;
    old_content?: string;
    new_content?: string;
  }>;
  base_commit: string;
}

export interface PastReview {
  attempt: number;
  state: string;
  state_local_index: number;
  paused_at: string;
  decision_action: string | null;
  decided_at: string | null;
  inline_comments: Array<{ id: string; file: string; line: number | null; body: string }>;
  comment_threads: Array<{
    id: string;
    comment_id: string;
    messages: Array<{ id: string; role: string; body: string; timestamp: string | null }>;
    agent_last_reviewed_at: string | null;
  }>;
}

interface DebugReviewLayoutProps {
  runId: string;
  issueId: string;
  state: string;
  snapshot: DebugReviewSnapshot;
  /**
   * Submits the debug decision. Comments are no longer passed on the wire —
   * the daemon persists each comment via PUT as the user authors it, and the
   * reducer bundles them from `Issue.inline_comments` at decision time.
   * Any free-form "Overall feedback" is persisted just before this is called.
   */
  onSubmit: (action: DebugAction) => Promise<void>;
  /** When true, suppress all mutation affordances and hide the action bar. */
  readOnly?: boolean;
  /** When readOnly, the static comments + decision metadata to render. */
  pastReview?: PastReview | null;
}

/** Convert a raw snapshot diff_file entry to the ChangesetFile the DiffView expects. */
function toChangesetFile(
  f: DebugReviewSnapshot["diff_files"][number],
): ChangesetFile {
  const knownStatuses = new Set<FileStatus>(["added", "modified", "deleted", "renamed"]);
  const status: FileStatus = knownStatuses.has(f.status as FileStatus)
    ? (f.status as FileStatus)
    : "modified";
  return {
    path: f.path,
    status,
    old_path: f.old_path,
    language: f.language,
    additions: f.additions ?? 0,
    deletions: f.deletions ?? 0,
    diff: f.diff ?? "",
    old_content: f.old_content,
    new_content: f.new_content,
  };
}

/**
 * Build a DiffViewOverlay from the flat InlineComment[] produced by useDraftComments.
 *
 * InlineComment uses { file, line, body } where `line` is the new-side line number.
 * ReviewComment used by DiffView adds a `side` field. We map all inline comments to
 * side="new" for simplicity — the debug review doesn't require old-side comments.
 */
function buildOverlay(
  comments: InlineComment[],
  onAdd: (c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => void,
  onRemove: (idx: number) => void,
  openDraftKey: string | null,
  setOpenDraftKey: (k: string | null) => void,
  draftBody: string,
  setDraftBody: (v: string) => void,
  threadFor: (commentId: string) => ThreadView | undefined,
  onReply: (commentId: string, body: string) => Promise<void>,
  readOnly: boolean,
): DiffViewOverlay {
  // Map InlineComment → ReviewComment for the DiffView API
  const reviewComments: ReviewComment[] = comments
    .filter((c) => c.line !== null)
    .map((c) => ({ id: c.id, file: c.file, line: c.line as number, side: "new" as const, body: c.body }));

  const draftFileLineKey = (file: string, side: "old" | "new", line: number) =>
    `${file}:${side}:${line}`;

  return {
    commentsForLine: (file, side, line) =>
      reviewComments.filter(
        (c) => c.file === file && c.side === side && c.line === line,
      ),

    draftForLine: (file, side, line) => {
      const key = draftFileLineKey(file, side, line);
      return openDraftKey === key ? draftBody : undefined;
    },

    globalIndexOf: (c: ReviewComment) => {
      // Find the global index of this ReviewComment in the underlying InlineComment array
      return comments.findIndex(
        (ic) => ic.file === c.file && ic.line === c.line && ic.body === c.body,
      );
    },

    onOpenDraft: (side, line) => {
      // We need the file path from context — DiffView passes side+line only.
      // The file is captured via closure in the renderMain function below.
      setOpenDraftKey(`__current__:${side}:${line}`);
      setDraftBody("");
    },

    onUpdateDraft: (_side, _line, body) => {
      setDraftBody(body);
    },

    onSaveDraft: (_side, _line) => {
      // File path is injected at call site via wrapOverlayForFile — base overlay is a no-op.
    },

    onCloseDraft: (_side, _line) => {
      setOpenDraftKey(null);
      setDraftBody("");
    },

    onEditComment: (index, body) => {
      // Editing: remove old + add updated. Index is into the reviewComments array.
      const original = comments[index];
      if (!original) return;
      onRemove(index);
      onAdd({ ...original, body });
    },

    onDeleteComment: (index) => {
      onRemove(index);
    },

    highlightedCommentIndex: null,

    threadFor,
    onReply,
    readOnly,
  };
}

/**
 * Returns a version of overlay whose draft open/save callbacks are bound to a specific file path.
 * DiffView calls onOpenDraft(side, line) without knowing the file — we close over it here.
 */
function wrapOverlayForFile(
  overlay: DiffViewOverlay,
  file: string,
  onAdd: (c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => void,
  openDraftKey: string | null,
  setOpenDraftKey: (k: string | null) => void,
  draftBody: string,
  setDraftBody: (v: string) => void,
): DiffViewOverlay {
  return {
    ...overlay,

    draftForLine: (f, side, line) => {
      const key = `${f}:${side}:${line}`;
      return openDraftKey === key ? draftBody : undefined;
    },

    onOpenDraft: (side, line) => {
      setOpenDraftKey(`${file}:${side}:${line}`);
      setDraftBody("");
    },

    onUpdateDraft: (_side, _line, body) => {
      setDraftBody(body);
    },

    onSaveDraft: (_side, line) => {
      if (draftBody.trim()) {
        onAdd({ file, line, body: draftBody.trim() });
      }
      setOpenDraftKey(null);
      setDraftBody("");
    },

    onCloseDraft: (_side, _line) => {
      setOpenDraftKey(null);
      setDraftBody("");
    },
  };
}

export function DebugReviewLayout({
  runId,
  issueId,
  state,
  snapshot,
  onSubmit,
  readOnly = false,
  pastReview = null,
}: DebugReviewLayoutProps) {
  // Always call hooks unconditionally (React rules), but use their data only in live mode.
  const live = useDraftComments(runId, issueId);
  const liveThreads = useCommentThreads(runId, issueId);

  // In readOnly mode, derive comments from pastReview instead of the live hook.
  const comments: InlineComment[] = useMemo(() => {
    if (readOnly && pastReview) {
      return pastReview.inline_comments.map((c) => ({
        id: c.id,
        file: c.file,
        line: c.line,
        body: c.body,
      }));
    }
    return live.comments;
  }, [readOnly, pastReview, live.comments]);

  // In readOnly mode, build a static thread lookup from pastReview.comment_threads.
  const pastThreadByCommentId = useMemo(() => {
    if (!(readOnly && pastReview)) return null;
    const map = new Map<string, ThreadView>();
    for (const t of pastReview.comment_threads) {
      if (t.messages.length === 0) continue;
      map.set(t.comment_id, {
        messages: t.messages.map((m) => ({
          id: m.id,
          role: m.role as "user" | "agent",
          body: m.body,
          timestamp: m.timestamp ?? "",
        })),
        agentReviewing: false,
      });
    }
    return map;
  }, [readOnly, pastReview]);

  const threadFor = useCallback(
    (commentId: string): ThreadView | undefined => {
      if (pastThreadByCommentId) {
        return pastThreadByCommentId.get(commentId);
      }
      return liveThreads.threadFor(commentId);
    },
    [pastThreadByCommentId, liveThreads.threadFor],
  );

  // No-op mutations for readOnly mode.
  const noOpAdd = useCallback((_c: Omit<InlineComment, "id"> & Partial<Pick<InlineComment, "id">>) => {}, []);
  const noOpRemove = useCallback((_idx: number) => {}, []);
  const noOpReply = useCallback(async (_commentId: string, _body: string) => {}, []);

  const add = readOnly ? noOpAdd : live.add;
  const remove = readOnly ? noOpRemove : live.remove;
  const reply = readOnly ? noOpReply : liveThreads.reply;

  const { clear } = live;
  const [submitting, setSubmitting] = useState(false);

  // Free-form, file-agnostic feedback bundled with line comments at submit time.
  const [overallFeedback, setOverallFeedback] = useState<string>("");
  useEffect(() => {
    const stored = localStorage.getItem(overallFeedbackKey(runId, issueId));
    if (stored) setOverallFeedback(stored);
  }, [runId, issueId]);
  useEffect(() => {
    localStorage.setItem(overallFeedbackKey(runId, issueId), overallFeedback);
  }, [runId, issueId, overallFeedback]);

  // Diff-view draft state (one open draft at a time across all real files)
  const [openDraftKey, setOpenDraftKey] = useState<string | null>(null);
  const [draftBody, setDraftBody] = useState("");

  const baseOverlay = useMemo(
    () =>
      buildOverlay(
        comments,
        add,
        remove,
        openDraftKey,
        setOpenDraftKey,
        draftBody,
        setDraftBody,
        threadFor,
        reply,
        readOnly,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [comments, add, remove, openDraftKey, draftBody, threadFor, reply, readOnly],
  );

  // Result first — that's what the user looks at to decide what to do next.
  const virtualFiles = [
    {
      id: "result.json",
      label: "result.json",
      commentCount: comments.filter((c) => c.file === "result.json").length,
    },
    {
      id: "prompt.md",
      label: "prompt.md",
      commentCount: comments.filter((c) => c.file === "prompt.md").length,
    },
    {
      id: `flow.yml::${state}`,
      label: `flow.yml :: ${state}`,
      commentCount: comments.filter((c) => c.file === `flow.yml::${state}`).length,
    },
  ];

  const realFiles = snapshot.diff_files.map((f) => ({
    path: f.path,
    status: (["added", "modified", "deleted", "renamed"].includes(f.status)
      ? f.status
      : "modified") as FileStatus,
    commentCount: comments.filter((c) => c.file === f.path).length,
  }));

  // All file IDs (virtual + real) for collapse-all / expand-all tracking
  const allFileIds = useMemo(
    () => [...virtualFiles.map((f) => f.id), ...realFiles.map((f) => f.path)],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [snapshot, state],
  );

  // Track which file IDs are currently collapsed. Sticky sidebar selection
  // just scrolls to anchor; selectedId tracks which file is "active" visually.
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => new Set());
  const allCollapsed = allFileIds.length > 0 && allFileIds.every((id) => collapsedIds.has(id));

  const toggleCollapsed = useCallback(
    (id: string) =>
      setCollapsedIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    [],
  );
  const collapseAll = useCallback(
    () => setCollapsedIds(new Set(allFileIds)),
    [allFileIds],
  );
  const expandAll = useCallback(() => setCollapsedIds(new Set()), []);

  const [selectedId, setSelectedId] = useState<string>(virtualFiles[0].id);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    const el = document.getElementById(anchorForId(id));
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  const handleSubmit = async (action: DebugAction) => {
    setSubmitting(true);
    try {
      // Line-anchored comments are already persisted on the daemon by
      // useDraftComments (PUT on each `add`). The "Overall feedback"
      // textarea is composed at submit time and is NOT yet persisted —
      // PUT it now (awaited) before submitting the decision so the reducer
      // sees it in Issue.inline_comments when building the event payload.
      const trimmedOverall = overallFeedback.trim();
      if (trimmedOverall) {
        const id =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `overall-${Date.now()}`;
        const res = await fetch(
          `/api/runs/${runId}/issues/${issueId}/comments/${id}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              file: OVERALL_FEEDBACK_FILE,
              line: null,
              body: trimmedOverall,
            }),
          },
        );
        if (!res.ok) {
          throw new Error(
            `Failed to persist overall feedback: HTTP ${res.status}`,
          );
        }
      }
      await onSubmit(action);
      clear();
      setOverallFeedback("");
      localStorage.removeItem(overallFeedbackKey(runId, issueId));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("[DebugReviewLayout] submit failed:", err);
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      {readOnly && pastReview && (
        <div className="border-b border-[var(--border)] bg-[var(--subtle)] px-4 py-2 text-[11px] text-[var(--fg-muted)]">
          Past review — {pastReview.state}, v{pastReview.state_local_index}
          {pastReview.decision_action
            ? ` · decided ${pastReview.decision_action} on ${pastReview.decided_at}`
            : ` · undecided (run stopped)`}
        </div>
      )}
      <div className="max-w-[1280px] mx-auto px-6 py-6 pr-32">
        {/* Commit-card header */}
        <header className="rounded-lg border border-border bg-card p-5 mb-5">
          <div className="flex items-start gap-4">
            <div className="flex-1 min-w-0">
              <h1 className="text-[15px] font-semibold tracking-tight">
                orca · debug review
              </h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground font-mono">
                <span className="text-foreground/85">{runId}</span>
                <span className="text-muted-foreground/60">·</span>
                <span>
                  state{" "}
                  <span className="text-foreground bg-muted px-1.5 py-0.5 rounded">
                    {state}
                  </span>
                </span>
                <span className="text-muted-foreground/60">·</span>
                <span>
                  base{" "}
                  <span className="text-foreground bg-muted px-1.5 py-0.5 rounded">
                    {snapshot.base_commit.slice(0, 8)}
                  </span>
                </span>
              </div>
            </div>
            {!readOnly && (
              <div className="shrink-0">
                <ActionButton onSubmit={handleSubmit} disabled={submitting} />
              </div>
            )}
          </div>
        </header>

        {/* Two-pane layout */}
        <div className="flex gap-5 items-start">
          <div className="w-[260px] shrink-0 sticky top-6 h-[calc(100vh-3rem)] overflow-hidden">
            <FileTreeSidebar
              virtualFiles={virtualFiles}
              realFiles={realFiles}
              selectedId={selectedId}
              onSelect={handleSelect}
            />
          </div>
          <main className="flex-1 min-w-0 space-y-4">
            {/* Stacked file feed toolbar */}
            <div className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-2">
              <div className="text-[12px] text-muted-foreground">
                <span className="font-semibold text-foreground">{allFileIds.length}</span>{" "}
                {allFileIds.length === 1 ? "file" : "files"} ·{" "}
                <span className="font-semibold text-foreground">{virtualFiles.length}</span> review{" "}
                {virtualFiles.length === 1 ? "surface" : "surfaces"} ·{" "}
                <span className="font-semibold text-foreground">{realFiles.length}</span> changeset{" "}
                {realFiles.length === 1 ? "file" : "files"}
              </div>
              <button
                type="button"
                onClick={allCollapsed ? expandAll : collapseAll}
                className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground cursor-pointer transition-colors"
              >
                {allCollapsed ? (
                  <>
                    <ChevronsUpDown size={13} />
                    Expand all
                  </>
                ) : (
                  <>
                    <ChevronsDownUp size={13} />
                    Collapse all
                  </>
                )}
              </button>
            </div>

            {/* Overall feedback — bundled into the comment payload at submit time */}
            {!readOnly && <div className="rounded-lg border border-border bg-card overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-muted/30">
                <MessageSquare size={14} className="text-muted-foreground shrink-0" />
                <span className="text-[13px] font-semibold">Overall feedback</span>
                <span className="text-[11px] text-muted-foreground/80">
                  optional · sent to the agent on Modify & restart
                </span>
                {overallFeedback.trim().length > 0 ? (
                  <span className="ml-auto text-[11px] text-primary font-medium bg-primary/10 px-2 py-0.5 rounded-full">
                    {overallFeedback.trim().length} chars
                  </span>
                ) : null}
              </div>
              <div className="px-4 py-3">
                <textarea
                  value={overallFeedback}
                  onChange={(e) => setOverallFeedback(e.target.value)}
                  rows={3}
                  placeholder="Anything you want the agent to know that isn't tied to a specific line — overall direction, missing context, follow-up tasks…"
                  className={cn(
                    "w-full px-3 py-2 text-[13px] font-sans resize-y",
                    "bg-background border border-border rounded-md",
                    "placeholder:text-muted-foreground/70",
                    "outline-none focus:border-primary/50 focus-visible:ring-0 transition-colors",
                  )}
                />
              </div>
            </div>}

            {/* Virtual review surfaces — result first */}
            <VirtualFileCard
              id="result.json"
              anchorId={anchorForId("result.json")}
              label="Worker result"
              content={JSON.stringify(snapshot.worker_result, null, 2)}
              language="json"
              comments={comments}
              onAddComment={add}
              onRemoveComment={remove}
              collapsed={collapsedIds.has("result.json")}
              onToggleCollapsed={() => toggleCollapsed("result.json")}
              threadFor={threadFor}
              onReply={reply}
              readOnly={readOnly}
            />
            <VirtualFileCard
              id="prompt.md"
              anchorId={anchorForId("prompt.md")}
              label="Rendered prompt"
              content={snapshot.rendered_prompt}
              language="markdown"
              comments={comments}
              onAddComment={add}
              onRemoveComment={remove}
              collapsed={collapsedIds.has("prompt.md")}
              onToggleCollapsed={() => toggleCollapsed("prompt.md")}
              threadFor={threadFor}
              onReply={reply}
              readOnly={readOnly}
            />
            <VirtualFileCard
              id={`flow.yml::${state}`}
              anchorId={anchorForId(`flow.yml::${state}`)}
              label={`flow.yml :: ${state}`}
              content={snapshot.config_slice}
              language="yaml"
              comments={comments}
              onAddComment={add}
              onRemoveComment={remove}
              collapsed={collapsedIds.has(`flow.yml::${state}`)}
              onToggleCollapsed={() => toggleCollapsed(`flow.yml::${state}`)}
              threadFor={threadFor}
              onReply={reply}
              readOnly={readOnly}
            />

            {/* Real diff files */}
            {snapshot.diff_files.map((rawFile) => {
              const changesetFile = toChangesetFile(rawFile);
              const overlay = wrapOverlayForFile(
                baseOverlay,
                rawFile.path,
                add,
                openDraftKey,
                setOpenDraftKey,
                draftBody,
                setDraftBody,
              );
              const commentCount = comments.filter((c) => c.file === rawFile.path).length;
              return (
                <DiffFileCard
                  key={rawFile.path}
                  anchorId={anchorForId(rawFile.path)}
                  file={changesetFile}
                  overlay={overlay}
                  collapsed={collapsedIds.has(rawFile.path)}
                  onToggleCollapsed={() => toggleCollapsed(rawFile.path)}
                  commentCount={commentCount}
                />
              );
            })}
          </main>
        </div>
      </div>
    </div>
  );
}
