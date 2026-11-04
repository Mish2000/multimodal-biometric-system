import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { PasswordField } from '../PasswordField'
import { useSession } from '../session'
import { errorText } from '../texts'

// The screen that a reset link opens (H32): the main process holds the link's token and adds it to these
// requests. The new password has the meter of registration (H30); after it, the account signs in as usual.
export function ResetPassword() {
  const { call, t } = useSession()
  const [state, setState] = useState<'checking' | 'ready' | 'invalid' | 'done'>('checking')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void call('checkResetLink').then((result) => setState(result.ok ? 'ready' : 'invalid'))
  }, [call])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (password !== repeat) {
      setError(t.passwordsDiffer)
      return
    }
    setBusy(true)
    setError('')
    const result = await call('completeReset', { password })
    setBusy(false)
    if (result.ok) {
      setPassword('')
      setRepeat('')
      setState('done')
    } else if (result.error === 'invalid_reset_link') setState('invalid')
    else setError(errorText(result, t))
  }

  return (
    <main className="narrow">
      <h1>{t.choosePassword}</h1>
      {state === 'checking' && <p className="aside">{t.checkingLink}</p>}
      {state === 'invalid' && (
        <>
          <p className="error" role="alert">
            {t.errors.invalid_reset_link}
          </p>
          <p className="aside">
            <Link to="/forgot-password">{t.askNewLink}</Link>
          </p>
        </>
      )}
      {state === 'done' && (
        <>
          <p className="ok" role="status">
            {t.passwordReset}
          </p>
          <p className="aside">
            <Link to="/sign-in">{t.toSignIn}</Link>
          </p>
        </>
      )}
      {state === 'ready' && (
        <>
          <p className="lead">{t.newPasswordLead}</p>
          <form onSubmit={submit} noValidate>
            <PasswordField label={t.newPassword} value={password} onChange={setPassword} autoComplete="new-password" meter />
            <PasswordField label={t.repeatPassword} value={repeat} onChange={setRepeat} autoComplete="new-password" />
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" disabled={busy || !password || !repeat}>
              {busy ? t.saving : t.saveNewPassword}
            </button>
          </form>
        </>
      )}
    </main>
  )
}
