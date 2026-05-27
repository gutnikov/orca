import { PrettyResultView } from "@/components/review/PrettyResultView"

interface Props {
  result: Record<string, unknown> | null
  activeSession: boolean
}

export function RunResultTab({ result, activeSession }: Props) {
  if (activeSession) {
    return (
      <div className="px-6 py-8 text-center text-sm text-muted-foreground italic">
        Waiting for result…
      </div>
    )
  }
  if (!result) {
    return (
      <div className="px-6 py-8 text-center text-sm text-muted-foreground italic">
        No result available for this session.
      </div>
    )
  }
  return <PrettyResultView result={result} />
}
