import { Card } from "@/components/ui/card"
import type { ExplainInput } from "@/lib/explain"
import { ExplainMarkdown } from "./ExplainMarkdown"

export function InputCard({ input }: { input: ExplainInput }) {
  const fields = input.fields ? Object.entries(input.fields) : []
  const title = input.title ?? "Input"
  const fieldsLabel = input.fields_label ?? "Fields seeded into the run"
  return (
    <Card className="p-0 gap-0 overflow-hidden">
      <div className="px-4 py-3 bg-card/85 border-b">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold">
          {title}
        </div>
      </div>
      <div className="p-4 space-y-3">
        <ExplainMarkdown content={input.description} />
        {fields.length > 0 ? (
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5">
              {fieldsLabel}
            </div>
            <div className="rounded-md border bg-muted/30">
              <table className="w-full text-xs">
                <tbody>
                  {fields.map(([k, v]) => (
                    <tr key={k} className="border-b last:border-b-0">
                      <td className="px-2 py-1 font-mono font-semibold w-1/3 align-top">{k}</td>
                      <td className="px-2 py-1 font-mono text-muted-foreground break-all">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  )
}
