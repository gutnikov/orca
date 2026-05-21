import type { FormResponse } from "@/lib/schema"

const tsDiffAdded = `@@ -0,0 +1,8 @@
+export function greet(name: string): string {
+  if (!name) {
+    throw new Error("name required")
+  }
+  return \`Hello, \${name}!\`
+}
+
+export const VERSION = "1.0.0"
`

const tsDiffModified = `@@ -1,9 +1,12 @@
 import { useState } from "react"
+import { useMemo } from "react"

 export function Counter() {
-  const [count, setCount] = useState(0)
+  const [count, setCount] = useState<number>(0)
+  const doubled = useMemo(() => count * 2, [count])
   return (
     <div>
       <p>Count: {count}</p>
+      <p>Doubled: {doubled}</p>
       <button onClick={() => setCount(count + 1)}>+</button>
     </div>
   )
`

const tsRenamed = `@@ -1,5 +1,5 @@
-export function oldName() {
-  return "deprecated"
+export function newName() {
+  return "renamed"
 }
`

const deletedDiff = `@@ -1,4 +0,0 @@
-// This file is being removed
-export const DEAD = true
-
-export default DEAD
`

export const demoForm: FormResponse = {
  run_id: "demo",
  issue_id: "demo",
  schema: {
    title: "Review proposed changes",
    description:
      "The worker has proposed these changes. Leave line-anchored comments where you'd like adjustments. At least one comment is required.",
    submit_label: "Submit review",
    cancel_label: "Reject",
    steps: [
      {
        blocks: [
          {
            kind: "markdown",
            content:
              "**Heads up:** this is a demo of the new changeset block. Hover any line to add a comment.",
          },
          {
            kind: "assertions",
            criteria: [
              {
                name: "uses_oauth_provider",
                status: "passed",
                summary: "Calls the OAuth provider's login URL",
                detail: "Found `await provider.login()` at `src/lib/greet.ts:5` — passes.",
              },
              {
                name: "no_password_in_logs",
                status: "passed",
                summary: "Password is never logged in plaintext",
              },
              {
                name: "returns_session_token",
                status: "failed",
                summary: "Session token is missing from the final response",
                detail:
                  "Expected `response.session_token` to be a non-empty string. Got `undefined`. The implementation returns the user object but doesn't include the freshly-minted token in the wire format.",
              },
              {
                name: "rate_limited",
                status: "skipped",
                summary: "Rate limiter check (not applicable for this run)",
              },
            ],
          },
          {
            kind: "changeset",
            name: "review",
            require_comment: true,
            files: [
              {
                path: "src/lib/greet.ts",
                status: "added",
                language: "typescript",
                additions: 8,
                deletions: 0,
                diff: tsDiffAdded,
                new_content:
                  'export function greet(name: string): string {\n  if (!name) {\n    throw new Error("name required")\n  }\n  return `Hello, ${name}!`\n}\n\nexport const VERSION = "1.0.0"\n',
              },
              {
                path: "src/components/Counter.tsx",
                status: "modified",
                language: "typescript",
                additions: 3,
                deletions: 1,
                diff: tsDiffModified,
                old_content:
                  'import { useState } from "react"\n\nexport function Counter() {\n  const [count, setCount] = useState(0)\n  return (\n    <div>\n      <p>Count: {count}</p>\n      <button onClick={() => setCount(count + 1)}>+</button>\n    </div>\n  )\n}\n',
                new_content:
                  'import { useState } from "react"\nimport { useMemo } from "react"\n\nexport function Counter() {\n  const [count, setCount] = useState<number>(0)\n  const doubled = useMemo(() => count * 2, [count])\n  return (\n    <div>\n      <p>Count: {count}</p>\n      <p>Doubled: {doubled}</p>\n      <button onClick={() => setCount(count + 1)}>+</button>\n    </div>\n  )\n}\n',
              },
              {
                path: "src/lib/names.ts",
                old_path: "src/lib/oldNames.ts",
                status: "renamed",
                language: "typescript",
                additions: 2,
                deletions: 2,
                diff: tsRenamed,
              },
              {
                path: "src/lib/dead.ts",
                status: "deleted",
                language: "typescript",
                additions: 0,
                deletions: 4,
                diff: deletedDiff,
              },
            ],
          },
        ],
      },
    ],
  },
  context: {
    state: "review",
    reason: "Worker proposed changes; awaiting human review.",
    started_waiting_at: new Date().toISOString(),
  },
}
