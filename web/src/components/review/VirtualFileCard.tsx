import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { InlineComment } from "./useDraftComments";

interface VirtualFileCardProps {
  id: string;
  label: string;
  content: string;
  language: "markdown" | "json" | "yaml" | "plain";
  comments: InlineComment[];
  onAddComment: (c: InlineComment) => void;
  onRemoveComment: (idx: number) => void;
}

/** Inline mini-composer that appears below a specific line. */
function LineComposer({
  fileId,
  line,
  onAdd,
  onCancel,
}: {
  fileId: string;
  line: number;
  onAdd: (c: InlineComment) => void;
  onCancel: () => void;
}) {
  const [body, setBody] = useState("");
  return (
    <div className="mx-10 my-1 flex flex-col gap-1">
      <Textarea
        autoFocus
        rows={2}
        className="text-xs font-sans resize-none"
        placeholder="Leave a comment…"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && body.trim()) {
            onAdd({ file: fileId, line, body: body.trim() });
            onCancel();
          }
        }}
      />
      <div className="flex gap-1 justify-end">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={!body.trim()}
          onClick={() => {
            if (body.trim()) {
              onAdd({ file: fileId, line, body: body.trim() });
              onCancel();
            }
          }}
        >
          Add comment
        </Button>
      </div>
    </div>
  );
}

export function VirtualFileCard({
  id,
  label,
  content,
  language,
  comments,
  onAddComment,
  onRemoveComment,
}: VirtualFileCardProps) {
  const [composingLine, setComposingLine] = useState<number | null>(null);
  const lines = content.split("\n");

  // Build a lookup: lineNumber → index in the global comments array
  const commentsByLine = new Map<number, Array<{ comment: InlineComment; globalIdx: number }>>();
  comments.forEach((c, globalIdx) => {
    if (c.file === id && c.line !== null) {
      const bucket = commentsByLine.get(c.line) ?? [];
      bucket.push({ comment: c, globalIdx });
      commentsByLine.set(c.line, bucket);
    }
  });

  return (
    <div className="virtual-file-card border rounded bg-white dark:bg-zinc-900">
      <div className="px-4 py-2 border-b bg-gray-50 dark:bg-zinc-800 text-sm font-medium flex items-center gap-2">
        <span className="opacity-60">virtual file</span>
        <span>{label}</span>
        <span className="ml-auto text-xs opacity-50">{language}</span>
      </div>
      <div className="font-mono text-xs leading-5">
        {lines.map((line, idx) => {
          const lineNumber = idx + 1;
          const lineComments = commentsByLine.get(lineNumber) ?? [];
          const isComposing = composingLine === lineNumber;
          return (
            <div key={idx}>
              <div
                className="flex hover:bg-gray-50 dark:hover:bg-zinc-800 group cursor-pointer"
                onClick={() => setComposingLine(lineNumber)}
                title="Click to add a comment"
              >
                <span className="w-10 px-2 text-right opacity-40 select-none shrink-0">
                  {lineNumber}
                </span>
                <span className="flex-1 px-2 whitespace-pre">{line || " "}</span>
                <span className="opacity-0 group-hover:opacity-40 pr-2 text-[10px] self-center shrink-0">
                  +
                </span>
              </div>

              {/* Inline comments for this line */}
              {lineComments.map(({ comment, globalIdx }) => (
                <div
                  key={globalIdx}
                  className="mx-10 my-1 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded px-3 py-1.5 flex items-start gap-2"
                >
                  <span className="flex-1 text-xs whitespace-pre-wrap">{comment.body}</span>
                  <button
                    type="button"
                    onClick={() => onRemoveComment(globalIdx)}
                    className="text-xs opacity-40 hover:opacity-100 shrink-0 mt-0.5"
                    aria-label="Remove comment"
                  >
                    ✕
                  </button>
                </div>
              ))}

              {/* Composer that opens when this line is clicked */}
              {isComposing && (
                <LineComposer
                  fileId={id}
                  line={lineNumber}
                  onAdd={onAddComment}
                  onCancel={() => setComposingLine(null)}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
