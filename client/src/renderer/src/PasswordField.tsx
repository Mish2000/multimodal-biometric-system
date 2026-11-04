import { useId, useState } from 'react'
import { checkPassword, STRENGTHS } from '../../shared/password'
import { useSession } from './session'
import type { Texts } from './texts'

// A password input with the eye that shows or hides what is typed (H30), as large products offer it. The
// eye sits at the end of the line in either direction; the password itself is always typed left to right.
export function RevealInput({
  id,
  value,
  onChange,
  autoComplete,
  label,
  placeholder,
  describedBy,
}: {
  id?: string | undefined
  value: string
  onChange(value: string): void
  autoComplete?: string | undefined
  label?: string | undefined
  placeholder?: string | undefined
  describedBy?: string | undefined
}) {
  const { t } = useSession()
  const own = useId()
  const inputId = id ?? own
  const [shown, setShown] = useState(false)
  return (
    <div className="reveal">
      <input
        id={inputId}
        type={shown ? 'text' : 'password'}
        value={value}
        dir="ltr"
        autoComplete={autoComplete}
        autoCapitalize="off"
        spellCheck={false}
        aria-label={label}
        aria-describedby={describedBy}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <button
        type="button"
        className="eye"
        aria-label={shown ? t.hidePassword : t.showPassword}
        aria-controls={inputId}
        title={shown ? t.hidePassword : t.showPassword}
        onClick={() => setShown(!shown)}
      >
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {shown && <path d="M4 4l16 16" />}
        </svg>
      </button>
    </div>
  )
}

interface PasswordFieldProps {
  label: string
  value: string
  onChange(value: string): void
  autoComplete: string
  hint?: string | undefined
  // A new password shows the strength meter and the rules under it (H30).
  meter?: boolean
}

export function PasswordField({ label, value, onChange, autoComplete, hint, meter = false }: PasswordFieldProps) {
  const id = useId()
  const described = meter ? `${id}-strength` : hint ? `${id}-hint` : undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <RevealInput id={id} value={value} onChange={onChange} autoComplete={autoComplete} describedBy={described} />
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {meter && <PasswordStrength id={`${id}-strength`} password={value} />}
    </div>
  )
}

// The meter's four levels, as the supervisor set them: invalid, weak, medium, strong (H30). It changes with
// every character typed; under it the three required rules and the two optional ones, each marked.
export function PasswordStrength({ id, password }: { id: string; password: string }) {
  const { t } = useSession()
  const check = checkPassword(password)
  const typed = password !== ''
  const rules: Array<[keyof Texts['rules'], boolean, boolean]> = [
    ['length', check.length, true],
    ['uppercase', check.uppercase, true],
    ['digit', check.digit, true],
    ['lowercase', check.lowercase, false],
    ['special', check.special, false],
  ]
  return (
    <div className="strength" id={id}>
      {typed && (
        <div className={`meter ${check.strength}`} data-level={STRENGTHS.indexOf(check.strength) + 1}>
          <div className="bars" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
          <p role="status">
            {t.strengthLabel}: <strong>{t.strengths[check.strength]}</strong>
          </p>
        </div>
      )}
      <ul className="rules">
        {rules.map(([rule, met, required]) => (
          <li key={rule} className={met ? 'met' : typed && required ? 'missing' : 'open'}>
            <span className="mark" aria-hidden="true">
              {met ? '✓' : required ? '•' : '+'}
            </span>
            {t.rules[rule]}
            <span className="visually-hidden">, {met ? t.ruleMet : t.ruleMissing}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
