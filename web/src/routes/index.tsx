import { createFileRoute } from "@tanstack/react-router"

export const Route = createFileRoute("/")({
  component: HomePage,
})

function HomePage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <h1 className="text-4xl font-semibold tracking-tight">Hello, Orca</h1>
    </main>
  )
}
