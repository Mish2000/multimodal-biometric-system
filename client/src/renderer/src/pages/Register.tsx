import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { Account } from '../../../shared/bridge'
import { Field } from '../Field'
import { useSession } from '../session'
import { errorText } from '../texts'

export function Register() {
  const { call, signedIn } = useSession()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nationalId, setNationalId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    const created = await call('register', { username, email, password, national_id: nationalId })
    if (!created.ok) {
      setBusy(false)
      setError(errorText(created))
      return
    }
    // The new account signs in at once with what was just typed.
    const result = await call<{ account: Account }>('login', { login: username, password })
    setBusy(false)
    if (result.ok) signedIn(result.data.account)
    else setError(errorText(result))
  }

  return (
    <main className="narrow">
      <h1>חשבון חדש</h1>
      <form onSubmit={submit} noValidate>
        <Field
          label="שם משתמש"
          value={username}
          onChange={setUsername}
          autoComplete="username"
          hint="3 עד 32 אותיות או ספרות, בכל שפה; מותר . _ - באמצע."
        />
        <Field label="אימייל" type="email" value={email} onChange={setEmail} autoComplete="email" dir="ltr" />
        <Field
          label="סיסמה"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          dir="ltr"
          hint="לפחות 12 תווים. אין חובה של סימנים או אותיות גדולות."
        />
        <Field
          label="מספר זהות"
          value={nationalId}
          onChange={setNationalId}
          autoComplete="off"
          dir="ltr"
          inputMode="numeric"
          hint="המספר לא נשמר. נשמר רק ערך חד-כיווני שלו (HMAC), שמונע הרשמה כפולה."
        />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !username || !email || !password || !nationalId}>
          {busy ? 'יוצרים חשבון…' : 'יצירת החשבון'}
        </button>
      </form>
      <p className="aside">
        כבר יש לך חשבון? <Link to="/sign-in">לכניסה</Link>
      </p>
    </main>
  )
}
