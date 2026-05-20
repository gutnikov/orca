import { Button } from "@/components/ui/button"

type Props = {
  stepIdx: number
  totalSteps: number
  cancelLabel?: string
  submitLabel?: string
  onBack: () => void
  onNext: () => void
  onSubmit: () => void
  onCancel: () => void
  submitting: boolean
}

export function FormFooter({
  stepIdx,
  totalSteps,
  cancelLabel,
  submitLabel,
  onBack,
  onNext,
  onSubmit,
  onCancel,
  submitting,
}: Props) {
  const lastStep = stepIdx === totalSteps - 1
  return (
    <div className="flex justify-between items-center mt-6 gap-2">
      <div>
        {cancelLabel ? (
          <Button variant="ghost" type="button" onClick={onCancel} disabled={submitting}>
            {cancelLabel}
          </Button>
        ) : null}
      </div>
      <div className="flex gap-2">
        {stepIdx > 0 ? (
          <Button variant="outline" type="button" onClick={onBack} disabled={submitting}>
            Back
          </Button>
        ) : null}
        {lastStep ? (
          <Button type="button" onClick={onSubmit} disabled={submitting}>
            {submitting ? "Submitting…" : submitLabel ?? "Submit"}
          </Button>
        ) : (
          <Button type="button" onClick={onNext} disabled={submitting}>
            Next
          </Button>
        )}
      </div>
    </div>
  )
}
