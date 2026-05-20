import { Controller, type Control } from "react-hook-form"
import { FormControl, FormDescription, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Textarea } from "@/components/ui/textarea"
import type { FieldBlock } from "@/lib/schema"
import { humanizeError } from "../errorMessages"

export function TextareaField({
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
        pattern: field.pattern ? new RegExp(field.pattern) : undefined,
      }}
      render={({ field: ctrl, fieldState }) => (
        <FormItem>
          <FormLabel>
            {field.label}
            {field.required ? <span className="text-destructive ml-1">*</span> : null}
          </FormLabel>
          <FormControl>
            <Textarea
              placeholder={field.placeholder}
              rows={field.rows ?? 4}
              value={(ctrl.value ?? "") as string}
              onChange={ctrl.onChange}
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
