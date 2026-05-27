import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "@tanstack/react-router"
import { router } from "./router"
import "./styles/globals.css"

// Theme initialization happens in useTheme.ts (imported via app-shell).
// Importing the module applies the stored/system preference before first paint.
import "./hooks/useTheme"

const rootEl = document.getElementById("root")
if (!rootEl) throw new Error("Root element #root not found")

createRoot(rootEl).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
