import { createFileRoute } from "@tanstack/react-router"
import { FormPage } from "@/components/forms/FormPage"
import { demoForm } from "./-review-demo.fixtures"

export const Route = createFileRoute("/review-demo")({
  component: ReviewDemoPage,
})

function ReviewDemoPage() {
  return <FormPage data={demoForm} />
}
