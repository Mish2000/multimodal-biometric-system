import { useId, type HTMLInputTypeAttribute } from 'react'

interface FieldProps {
  label: string
  value: string
  onChange(value: string): void
  type?: HTMLInputTypeAttribute
  autoComplete?: string
  dir?: 'ltr' | 'rtl' | 'auto'
  inputMode?: 'text' | 'numeric' | 'email'
  hint?: string
}

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
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && <p className="hint">{hint}</p>}
    </div>
  )
}
