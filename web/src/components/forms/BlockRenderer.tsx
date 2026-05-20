import { lazy, Suspense } from "react"
import type { Control } from "react-hook-form"
import type { FormBlock } from "@/lib/schema"
import { FieldBlock } from "./blocks/FieldBlock"

const MarkdownBlock = lazy(() => import("./blocks/MarkdownBlock"))
const CodeBlock = lazy(() => import("./blocks/CodeBlock"))
const DiffBlock = lazy(() => import("./blocks/DiffBlock"))

const BlockSkeleton = () => <div className="h-12 animate-pulse rounded bg-muted" />

export function BlockRenderer({
  block,
  control,
}: {
  block: FormBlock
  control: Control<Record<string, unknown>>
}) {
  switch (block.kind) {
    case "field":
      return <FieldBlock field={block} control={control} />
    case "markdown":
      return (
        <Suspense fallback={<BlockSkeleton />}>
          <MarkdownBlock content={block.content} />
        </Suspense>
      )
    case "code":
      return (
        <Suspense fallback={<BlockSkeleton />}>
          <CodeBlock content={block.content} language={block.language} />
        </Suspense>
      )
    case "diff":
      return (
        <Suspense fallback={<BlockSkeleton />}>
          <DiffBlock content={block.content} filename={block.filename} />
        </Suspense>
      )
  }
}
