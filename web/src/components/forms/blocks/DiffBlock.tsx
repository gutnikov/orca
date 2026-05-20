import ReactDiffViewer from "react-diff-viewer-continued"

function splitUnifiedDiff(text: string): { old: string; new: string } {
  const oldLines: string[] = []
  const newLines: string[] = []
  for (const line of text.split("\n")) {
    if (
      line.startsWith("---") ||
      line.startsWith("+++") ||
      line.startsWith("@@") ||
      line.startsWith("diff ") ||
      line.startsWith("index ")
    ) {
      continue
    }
    if (line.startsWith("-")) {
      oldLines.push(line.slice(1))
    } else if (line.startsWith("+")) {
      newLines.push(line.slice(1))
    } else {
      const stripped = line.startsWith(" ") ? line.slice(1) : line
      oldLines.push(stripped)
      newLines.push(stripped)
    }
  }
  return { old: oldLines.join("\n"), new: newLines.join("\n") }
}

export default function DiffBlock({ content, filename }: { content: string; filename?: string }) {
  const { old: oldCode, new: newCode } = splitUnifiedDiff(content)
  return (
    <div className="rounded-lg border overflow-hidden text-xs">
      {filename ? (
        <div className="bg-muted px-3 py-1.5 font-mono text-xs border-b">{filename}</div>
      ) : null}
      <ReactDiffViewer
        oldValue={oldCode}
        newValue={newCode}
        splitView={false}
        hideLineNumbers={false}
        useDarkTheme={false}
      />
    </div>
  )
}
