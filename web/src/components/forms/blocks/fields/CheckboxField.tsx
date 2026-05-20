import { Controller, type Control } from "react-hook-form"
import { FormControl, FormDescription, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Checkbox } from "@/components/ui/checkbox"
import type { FieldBlock } from "@/lib/schema"
import { humanizeError } from "../errorMessages"

export function CheckboxField({
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
        validate: (v) => (field.required ? v === true || "required" : true),
      }}
      render={({ field: ctrl, fieldState }) => (
        <FormItem className="flex flex-row items-start gap-3 space-y-0">
          <FormControl>
            <Checkbox
              checked={Boolean(ctrl.value)}
              onCheckedChange={(v) => ctrl.onChange(v === true)}
              onBlur={ctrl.onBlur}
              ref={ctrl.ref}
            />
          </FormControl>
          <div className="space-y-1 leading-none">
            <FormLabel>
              {field.label}
              {field.required ? <span className="text-destructive ml-1">*</span> : null}
            </FormLabel>
            {field.help ? <FormDescription>{field.help}</FormDescription> : null}
            <FormMessage>
              {fieldState.error ? humanizeError(fieldState.error.type ?? fieldState.error.message ?? "") : null}
            </FormMessage>
          </div>
        </FormItem>
      )}
    />
  )
}
