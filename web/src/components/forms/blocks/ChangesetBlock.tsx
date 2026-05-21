import { useController, type Control } from "react-hook-form"
import type { FormBlock, ReviewComment, ChangesetFile } from "@/lib/schema"
import { useChangesetState } from "./changeset/useChangesetState"
import { FileCard } from "./changeset/FileCard"

type Block = Extract<FormBlock, { kind: "changeset" }>

export default function ChangesetBlock({
  block,
  control,
}: {
  block: Block
  control: Control<Record<string, unknown>>
}) {
  const { field } = useController<Record<string, unknown>, string>({
    name: block.name,
    control,
    defaultValue: [] as ReviewComment[],
    rules: block.require_comment
      ? { validate: (v) => (Array.isArray(v) && v.length > 0) || "comment_required" }
      : undefined,
  })

  const state = useChangesetState({
    initialComments: (field.value as ReviewComment[]) ?? [],
    onChange: (next) => field.onChange(next),
    filePaths: block.files.map((f: ChangesetFile) => f.path),
  })

  return (
    <div className="space-y-4">
      <div className="text-xs text-muted-foreground font-mono">
        {block.files.length} file{block.files.length === 1 ? "" : "s"} changed · {state.comments.length}{" "}
        comment{state.comments.length === 1 ? "" : "s"}
      </div>
      <div className="space-y-3">
        {block.files.map((file: ChangesetFile) => (
          <FileCard
            key={file.path}
            file={file}
            collapsed={state.collapsed.has(file.path)}
            onToggleCollapse={() => state.toggleCollapse(file.path)}
            viewMode={state.viewMode.get(file.path) ?? "changes"}
            onSetMode={(m) => state.setFileMode(file.path, m)}
            commentCount={state.commentCountForFile(file.path)}
          >
            <pre className="p-4 text-xs font-mono whitespace-pre overflow-x-auto bg-muted/30">
              {file.diff}
            </pre>
          </FileCard>
        ))}
      </div>
    </div>
  )
}
