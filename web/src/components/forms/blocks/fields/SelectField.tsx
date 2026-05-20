import { Controller, type Control } from "react-hook-form"
import { FormControl, FormDescription, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { FieldBlock } from "@/lib/schema"
import { humanizeError } from "../errorMessages"

export function SelectField({
  field,
  control,
}: {
  field: FieldBlock
  control: Control<Record<string, unknown>>
}) {
  const options = field.options ?? []
  return (
    <Controller
      control={control}
      name={field.name}
      rules={{
        validate: (v) =>
          field.required ? (typeof v === "string" && v.length > 0) || "required" : true,
      }}
      render={({ field: ctrl, fieldState }) => (
        <FormItem>
          <FormLabel>
            {field.label}
            {field.required ? <span className="text-destructive ml-1">*</span> : null}
          </FormLabel>
          <Select onValueChange={ctrl.onChange} value={(ctrl.value ?? "") as string}>
            <FormControl>
              <SelectTrigger>
                <SelectValue placeholder={field.placeholder ?? "Select an option"} />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              {options.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {field.help ? <FormDescription>{field.help}</FormDescription> : null}
          <FormMessage>
            {fieldState.error ? humanizeError(fieldState.error.type ?? fieldState.error.message ?? "") : null}
          </FormMessage>
        </FormItem>
      )}
    />
  )
}
