import { useState } from "react"
import { useForm, FormProvider } from "react-hook-form"
import { toast } from "sonner"
import { Card, CardContent } from "@/components/ui/card"
import { schemaToDefaults, stepFieldNames, type FormResponse } from "@/lib/schema"
import {
  submitForm,
  ValidationError,
  FormExpiredError,
  FormAlreadySubmittedError,
} from "@/lib/api"
import { BlockRenderer } from "./BlockRenderer"
import { FormHeader } from "./FormHeader"
import { FormFooter } from "./FormFooter"
import { StepIndicator } from "./StepIndicator"
import { TerminalState, type TerminalVariant } from "./TerminalState"

export function FormPage({ data }: { data: FormResponse }) {
  const [stepIdx, setStepIdx] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState<TerminalVariant | null>(null)

  const form = useForm<Record<string, unknown>>({
    defaultValues: schemaToDefaults(data.schema),
    mode: "onChange",
  })

  if (done) return <TerminalState variant={done} />

  const step = data.schema.steps[stepIdx]
  const totalSteps = data.schema.steps.length
  const isLastStep = stepIdx === totalSteps - 1

  const handleErr = (e: unknown) => {
    if (e instanceof ValidationError) {
      for (const [name, code] of Object.entries(e.fieldErrors)) {
        form.setError(name, { type: code, message: code })
      }
      toast.error("Some fields need attention")
    } else if (e instanceof FormExpiredError) {
      setDone("expired")
    } else if (e instanceof FormAlreadySubmittedError) {
      setDone("already_submitted")
    } else {
      toast.error("Something went wrong")
    }
  }

  const submitDisabled = !form.formState.isValid
  const submitDisabledReason = submitDisabled
    ? "At least one comment is required to submit."
    : undefined

  const onNext = async () => {
    const ok = await form.trigger(stepFieldNames(step))
    if (ok) setStepIdx((i) => i + 1)
  }

  const onBack = () => setStepIdx((i) => i - 1)

  const onCancel = async () => {
    if (submitting) return
    setSubmitting(true)
    try {
      await submitForm(data.run_id, data.issue_id, { cancelled: true })
      setDone("cancelled")
    } catch (e) {
      handleErr(e)
    } finally {
      setSubmitting(false)
    }
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setSubmitting(true)
    try {
      await submitForm(data.run_id, data.issue_id, { values })
      setDone("submitted")
    } catch (e) {
      handleErr(e)
    } finally {
      setSubmitting(false)
    }
  })

  const hasChangeset = data.schema.steps.some((s) =>
    s.blocks.some((b) => b.kind === "changeset"),
  )
  const widthClass = hasChangeset ? "max-w-6xl" : "max-w-2xl"

  return (
    <main className={`${widthClass} mx-auto p-6`}>
      <FormHeader data={data} />
      <Card>
        <CardContent className="pt-6">
          <StepIndicator steps={data.schema.steps} current={stepIdx} />
          <FormProvider {...form}>
            <form onSubmit={(e) => e.preventDefault()} className="space-y-5">
              {step.blocks.map((block, i) => (
                <BlockRenderer key={i} block={block} control={form.control} />
              ))}
            </form>
          </FormProvider>
          <FormFooter
            stepIdx={stepIdx}
            totalSteps={totalSteps}
            cancelLabel={data.schema.cancel_label}
            submitLabel={data.schema.submit_label}
            onBack={onBack}
            onNext={onNext}
            onSubmit={onSubmit}
            onCancel={onCancel}
            submitting={submitting}
            submitDisabled={submitDisabled}
            submitDisabledReason={submitDisabledReason}
          />
        </CardContent>
      </Card>
      {!isLastStep ? null : (
        <p className="text-center text-xs text-muted-foreground mt-4">
          Submitting will resume the orca worker waiting on this form.
        </p>
      )}
    </main>
  )
}
