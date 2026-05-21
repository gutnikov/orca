import { createFileRoute } from "@tanstack/react-router"
import { ExplainPage } from "@/components/explain/ExplainPage"
import { demoExplanation } from "./-explain-demo.fixtures"

export const Route = createFileRoute("/explain-demo")({
  component: ExplainDemoPage,
})

function ExplainDemoPage() {
  return <ExplainPage data={demoExplanation} />
}
