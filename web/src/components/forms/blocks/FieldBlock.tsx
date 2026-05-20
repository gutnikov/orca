import type { Control } from "react-hook-form"
import type { FieldBlock as FieldBlockType } from "@/lib/schema"
import { TextField } from "./fields/TextField"
import { EmailField } from "./fields/EmailField"
import { PasswordField } from "./fields/PasswordField"
import { NumberField } from "./fields/NumberField"
import { CheckboxField } from "./fields/CheckboxField"
import { SelectField } from "./fields/SelectField"
import { TextareaField } from "./fields/TextareaField"
import { DateField } from "./fields/DateField"

export function FieldBlock({
  field,
  control,
}: {
  field: FieldBlockType
  control: Control<Record<string, unknown>>
}) {
  switch (field.type) {
    case "text":
      return <TextField field={field} control={control} />
    case "email":
      return <EmailField field={field} control={control} />
    case "password":
      return <PasswordField field={field} control={control} />
    case "number":
      return <NumberField field={field} control={control} />
    case "checkbox":
      return <CheckboxField field={field} control={control} />
    case "select":
      return <SelectField field={field} control={control} />
    case "textarea":
      return <TextareaField field={field} control={control} />
    case "date":
      return <DateField field={field} control={control} />
  }
}
