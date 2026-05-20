import { Controller, type Control } from "react-hook-form"
import { FormControl, FormDescription, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import type { FieldBlock } from "@/lib/schema"
import { humanizeError } from "../errorMessages"

type Props = {
  field: FieldBlock
  control: Control<Record<string, unknown>>
  inputType?: string
}

export function TextField({ field, control, inputType = "text" }: Props) {
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
            <Input
              type={inputType}
              placeholder={field.placeholder}
              value={(ctrl.value ?? "") as string}
              onChange={ctrl.onChange}
              onBlur={ctrl.onBlur}
              ref={ctrl.ref}
            />
          </FormControl>
          {field.help ? <FormDescription>{field.help}</FormDescription> : null}
          <FormMessage>{fieldState.error ? humanizeError(fieldState.error.type ?? fieldState.error.message ?? "") : null}</FormMessage>
        </FormItem>
      )}
    />
  )
}
