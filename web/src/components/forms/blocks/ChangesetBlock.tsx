import { useController, type Control } from "react-hook-form"
import type { FormBlock, ReviewComment } from "@/lib/schema"

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

  return (
    <div className="space-y-3">
      <div className="text-sm text-muted-foreground">
        {block.files.length} file{block.files.length === 1 ? "" : "s"} changed ·{" "}
        {(Array.isArray(field.value) ? field.value.length : 0)} comments
      </div>
      <ul className="space-y-1 font-mono text-xs">
        {block.files.map((f) => (
          <li key={f.path}>
            <span className="text-muted-foreground">{f.status}</span> {f.path}{" "}
            <span className="text-emerald-600">+{f.additions}</span>{" "}
            <span className="text-red-600">−{f.deletions}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
