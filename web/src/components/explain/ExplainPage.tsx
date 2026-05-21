import type { Explanation } from "@/lib/explain"
import { ExplainHeader } from "./ExplainHeader"
import { InputCard } from "./InputCard"
import { StateDiagram } from "./StateDiagram"
import { StateList } from "./StateList"
import { WalkthroughList } from "./WalkthroughList"

export function ExplainPage({ data }: { data: Explanation }) {
  return (
    <main className="max-w-5xl mx-auto p-6 space-y-8">
      <ExplainHeader data={data} />
      <StateDiagram source={data.diagram_mermaid} />
      {data.input ? <InputCard input={data.input} /> : null}
      <StateList states={data.states} />
      {data.walkthrough && data.walkthrough.length > 0 ? (
        <WalkthroughList steps={data.walkthrough} />
      ) : null}
    </main>
  )
}
