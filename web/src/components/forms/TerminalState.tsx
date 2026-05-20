import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { CheckCircle2, Clock, XCircle } from "lucide-react"

export type TerminalVariant = "submitted" | "cancelled" | "already_submitted" | "expired" | "not_found"

export function TerminalState({ variant }: { variant: TerminalVariant }) {
  if (variant === "expired") {
    return (
      <Layout>
        <Alert>
          <Clock className="h-4 w-4" />
          <AlertTitle>This form expired</AlertTitle>
          <AlertDescription>
            The worker is no longer waiting for this input. Check the run log to see what orca did next.
          </AlertDescription>
        </Alert>
      </Layout>
    )
  }
  if (variant === "not_found") {
    return (
      <Layout>
        <Alert>
          <XCircle className="h-4 w-4" />
          <AlertTitle>No form here</AlertTitle>
          <AlertDescription>This URL has no pending form.</AlertDescription>
        </Alert>
      </Layout>
    )
  }
  const heading =
    variant === "submitted"
      ? "Done — orca is continuing."
      : variant === "cancelled"
      ? "Cancelled — orca is continuing."
      : "This form was already completed."
  return (
    <Layout>
      <Alert>
        <CheckCircle2 className="h-4 w-4" />
        <AlertTitle>{heading}</AlertTitle>
        <AlertDescription>You can close this tab.</AlertDescription>
      </Alert>
      <div className="flex justify-center mt-4">
        <Button variant="ghost" onClick={() => window.close()}>
          Close tab
        </Button>
      </div>
    </Layout>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  return <main className="max-w-lg mx-auto p-8 mt-12">{children}</main>
}
