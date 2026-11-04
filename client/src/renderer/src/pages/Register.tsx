import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { Account } from '../../../shared/bridge'
import { Field } from '../Field'
import { LanguageSwitch } from '../LanguageSwitch'
import { PasswordField } from '../PasswordField'
import { useSession } from '../session'
import { errorText } from '../texts'

// A user account (H3) with its mobile phone (H29), a password under the rules of H30 with its meter, and
// the language of this screen as the account's (H31).
export function Register() {
  const { call, signedIn, t, language } = useSession()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [nationalId, setNationalId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    const created = await call('register', { username, email, phone, password, national_id: nationalId, language })
    if (!created.ok) {
      setBusy(false)
      setError(errorText(created, t))
      return
    }
    // The new account signs in at once with what was just typed.
    const result = await call<{ account: Account }>('login', { login: username, password })
    setBusy(false)
    if (result.ok) signedIn(result.data.account)
    else setError(errorText(result, t))
  }

  return (
    <main className="narrow">
      <LanguageSwitch />
      <h1>{t.newAccount}</h1>
      <form onSubmit={submit} noValidate>
        <Field label={t.username} value={username} onChange={setUsername} autoComplete="username" hint={t.usernameHint} />
        <Field label={t.email} type="email" value={email} onChange={setEmail} autoComplete="email" dir="ltr" />
        <Field
          label={t.phone}
          type="tel"
          value={phone}
          onChange={setPhone}
          autoComplete="tel"
          dir="ltr"
          inputMode="tel"
          hint={t.phoneHint}
        />
        <PasswordField label={t.password} value={password} onChange={setPassword} autoComplete="new-password" meter />
        <Field
          label={t.nationalId}
          value={nationalId}
          onChange={setNationalId}
          autoComplete="off"
          dir="ltr"
          inputMode="numeric"
          hint={t.nationalIdHint}
        />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !username || !email || !phone || !password || !nationalId}>
          {busy ? t.creatingAccount : t.createAccount}
        </button>
      </form>
      <p className="aside">
        {t.haveAccount} <Link to="/sign-in">{t.toSignIn}</Link>
      </p>
    </main>
  )
}
