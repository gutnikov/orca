import { useId } from "react"
import { Card } from "@/components/ui/card"
import { Collapsible } from "radix-ui"
import type { ChangesetFile } from "./types"
import type { ViewMode } from "./types"
import { FileHeader } from "./FileHeader"

export function FileCard({
  file,
  collapsed,
  onToggleCollapse,
  viewMode,
  onSetMode,
  commentCount,
  children,
}: {
  file: ChangesetFile
  collapsed: boolean
  onToggleCollapse: () => void
  viewMode: ViewMode
  onSetMode: (m: ViewMode) => void
  commentCount: number
  children: React.ReactNode
}) {
  const id = useId()
  const fullEnabled = typeof file.new_content === "string"

  return (
    <Card id={id} data-path={file.path} className="overflow-hidden p-0 gap-0">
      <Collapsible.Root open={!collapsed}>
        <FileHeader
          file={file}
          collapsed={collapsed}
          onToggleCollapse={onToggleCollapse}
          viewMode={viewMode}
          onSetMode={onSetMode}
          fullEnabled={fullEnabled}
          commentCount={commentCount}
        />
        <Collapsible.Content className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
          <div className="border-t">{children}</div>
        </Collapsible.Content>
      </Collapsible.Root>
    </Card>
  )
}
