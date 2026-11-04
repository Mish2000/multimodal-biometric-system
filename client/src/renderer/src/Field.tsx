import { useId, type HTMLInputTypeAttribute } from 'react'

interface FieldProps {
  label: string
  value: string
  onChange(value: string): void
  type?: HTMLInputTypeAttribute
  autoComplete?: string
  dir?: 'ltr' | 'rtl' | 'auto'
  inputMode?: 'text' | 'numeric' | 'email' | 'tel'
  hint?: string
}

// A labelled text field; passwords use PasswordField, which adds the eye (H30).
export function Field({ label, value, onChange, type = 'text', autoComplete, dir = 'auto', inputMode, hint }: FieldProps) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        dir={dir}
        autoComplete={autoComplete}
        inputMode={inputMode}
        spellCheck={false}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
    </div>
  )
}
