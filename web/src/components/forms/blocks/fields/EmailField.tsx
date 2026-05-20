import type { Control } from "react-hook-form"
import type { FieldBlock } from "@/lib/schema"
import { TextField } from "./TextField"

export function EmailField({ field, control }: { field: FieldBlock; control: Control<Record<string, unknown>> }) {
  return <TextField field={field} control={control} inputType="email" />
}
