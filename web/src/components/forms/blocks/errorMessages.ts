export function humanizeError(code: string): string {
  switch (code) {
    case "required":
      return "This field is required."
    case "type":
      return "Please enter a valid value."
    case "pattern":
      return "Value doesn't match the required format."
    case "min":
      return "Value is below the minimum allowed."
    case "max":
      return "Value is above the maximum allowed."
    case "unknown_field":
      return "Unexpected field."
    default:
      return code || "Invalid value."
  }
}
