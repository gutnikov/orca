import { Controller, type Control } from "react-hook-form"
import { FormControl, FormDescription, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import type { FieldBlock } from "@/lib/schema"
import { humanizeError } from "../errorMessages"

export function NumberField({
  field,
  control,
}: {
  field: FieldBlock
  control: Control<Record<string, unknown>>
}) {
  return (
    <Controller
      control={control}
      name={field.name}
      rules={{
        required: field.required ? "required" : false,
        min: field.min !== undefined ? { value: field.min, message: "min" } : undefined,
        max: field.max !== undefined ? { value: field.max, message: "max" } : undefined,
      }}
      render={({ field: ctrl, fieldState }) => (
        <FormItem>
          <FormLabel>
            {field.label}
            {field.required ? <span className="text-destructive ml-1">*</span> : null}
          </FormLabel>
          <FormControl>
            <Input
              type="number"
              placeholder={field.placeholder}
              min={field.min}
              max={field.max}
              step={field.step}
              value={ctrl.value === "" || ctrl.value === undefined || ctrl.value === null ? "" : String(ctrl.value)}
              onChange={(e) => {
                const v = e.target.value
                ctrl.onChange(v === "" ? "" : Number(v))
              }}
              onBlur={ctrl.onBlur}
              ref={ctrl.ref}
            />
          </FormControl>
          {field.help ? <FormDescription>{field.help}</FormDescription> : null}
          <FormMessage>
            {fieldState.error ? humanizeError(fieldState.error.type ?? fieldState.error.message ?? "") : null}
          </FormMessage>
        </FormItem>
      )}
    />
  )
}
