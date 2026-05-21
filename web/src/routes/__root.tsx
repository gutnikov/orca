import { createRootRoute, Outlet } from "@tanstack/react-router"
import { Toaster } from "@/components/ui/sonner"
import { ThemeToggle } from "@/components/ThemeToggle"

export const Route = createRootRoute({
  component: RootLayout,
})

function RootLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <ThemeToggle />
      <Outlet />
      <Toaster richColors position="top-right" />
    </div>
  )
}
