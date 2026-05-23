import { useMemo, useState } from "react";

import { ActionButton, type DebugAction } from "./ActionButton";
import { DiffView, type DiffViewOverlay } from "./DiffView";
import { FileTreeSidebar } from "./FileTreeSidebar";
import { VirtualFileCard } from "./VirtualFileCard";
import { useDraftComments, type InlineComment } from "./useDraftComments";
import type { ChangesetFile, FileStatus, ReviewComment } from "./types";

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

  const virtualFiles = [
    {
      id: "prompt.md",
      label: "prompt.md",
      commentCount: comments.filter((c) => c.file === "prompt.md").length,
    },
    {
      id: "result.json",
      label: "result.json",
      commentCount: comments.filter((c) => c.file === "result.json").length,
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

  const [selectedId, setSelectedId] = useState<string>(virtualFiles[0].id);

  const handleSubmit = async (action: DebugAction) => {
    setSubmitting(true);
    try {
      await onSubmit(action, comments);
      clear();
    } finally {
      setSubmitting(false);
    }
  };

  const renderMain = () => {
    if (selectedId === "prompt.md") {
      return (
        <VirtualFileCard
          id="prompt.md"
          label="Rendered prompt"
          content={snapshot.rendered_prompt}
          language="markdown"
          comments={comments}
          onAddComment={add}
          onRemoveComment={remove}
        />
      );
    }
    if (selectedId === "result.json") {
      return (
        <VirtualFileCard
          id="result.json"
          label="Worker result"
          content={JSON.stringify(snapshot.worker_result, null, 2)}
          language="json"
          comments={comments}
          onAddComment={add}
          onRemoveComment={remove}
        />
      );
    }
    if (selectedId.startsWith("flow.yml::")) {
      return (
        <VirtualFileCard
          id={selectedId}
          label={`flow.yml :: ${state}`}
          content={snapshot.config_slice}
          language="yaml"
          comments={comments}
          onAddComment={add}
          onRemoveComment={remove}
        />
      );
    }
    const rawFile = snapshot.diff_files.find((f) => f.path === selectedId);
    if (!rawFile) return null;
    const changesetFile = toChangesetFile(rawFile);
    const overlay = wrapOverlayForFile(
      baseOverlay,
      selectedId,
      add,
      openDraftKey,
      setOpenDraftKey,
      draftBody,
      setDraftBody,
    );
    return (
      <DiffView
        file={changesetFile}
        mode="changes"
        overlay={overlay}
      />
    );
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

        {/* Two-pane layout: sticky sidebar + scrollable main */}
        <div className="flex gap-5 items-start">
          <div className="w-[260px] shrink-0 sticky top-6 max-h-[calc(100vh-3rem)] overflow-hidden">
            <FileTreeSidebar
              virtualFiles={virtualFiles}
              realFiles={realFiles}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
          <main className="flex-1 min-w-0">{renderMain()}</main>
        </div>
      </div>
    </div>
  );
}
