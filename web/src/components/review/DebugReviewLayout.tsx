import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronsDownUp, ChevronsUpDown, MessageSquare } from "lucide-react";

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

interface DebugReviewLayoutProps {
  runId: string;
  issueId: string;
  state: string;
  snapshot: DebugReviewSnapshot;
  onSubmit: (action: DebugAction, comments: InlineComment[]) => Promise<void>;
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
  onAdd: (c: InlineComment) => void,
  onRemove: (idx: number) => void,
  openDraftKey: string | null,
  setOpenDraftKey: (k: string | null) => void,
  draftBody: string,
  setDraftBody: (v: string) => void,
): DiffViewOverlay {
  // Map InlineComment → ReviewComment for the DiffView API
  const reviewComments: ReviewComment[] = comments
    .filter((c) => c.line !== null)
    .map((c) => ({ file: c.file, line: c.line as number, side: "new" as const, body: c.body }));

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
  };
}

/**
 * Returns a version of overlay whose draft open/save callbacks are bound to a specific file path.
 * DiffView calls onOpenDraft(side, line) without knowing the file — we close over it here.
 */
function wrapOverlayForFile(
  overlay: DiffViewOverlay,
  file: string,
  onAdd: (c: InlineComment) => void,
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
}: DebugReviewLayoutProps) {
  const { comments, add, remove, clear } = useDraftComments(runId, issueId);
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
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [comments, add, remove, openDraftKey, draftBody],
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
      const trimmedOverall = overallFeedback.trim();
      const allComments: InlineComment[] = trimmedOverall
        ? [
            ...comments,
            { file: OVERALL_FEEDBACK_FILE, line: null, body: trimmedOverall },
          ]
        : comments;
      await onSubmit(action, allComments);
      clear();
      setOverallFeedback("");
      localStorage.removeItem(overallFeedbackKey(runId, issueId));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
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
            <div className="shrink-0">
              <ActionButton onSubmit={handleSubmit} disabled={submitting} />
            </div>
          </div>
        </header>

        {/* Two-pane layout */}
        <div className="flex gap-5 items-start">
          <div className="w-[260px] shrink-0 sticky top-6 max-h-[calc(100vh-3rem)] overflow-hidden">
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
            <div className="rounded-lg border border-border bg-card overflow-hidden">
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
            </div>

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
