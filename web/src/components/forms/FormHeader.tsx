import type { FormResponse } from "@/lib/schema"

export function FormHeader({ data }: { data: FormResponse }) {
  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight">{data.schema.title}</h1>
      {data.schema.description ? (
        <p className="text-muted-foreground mt-1 text-sm">{data.schema.description}</p>
      ) : null}
      {data.context.reason ? (
        <p className="text-muted-foreground mt-2 text-xs italic">
          {data.context.reason}
        </p>
      ) : null}
    </header>
  )
}
