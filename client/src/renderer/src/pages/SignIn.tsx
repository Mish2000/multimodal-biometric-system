import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { Account } from '../../../shared/bridge'
import { Field } from '../Field'
import { LanguageSwitch } from '../LanguageSwitch'
import { PasswordField } from '../PasswordField'
import { useSession } from '../session'
import { errorText } from '../texts'
import { Notice } from '../ui/Notice'

export function SignIn() {
  const { call, signedIn, notice, t, chosenLanguage } = useSession()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [server, setServer] = useState<'checking' | 'up' | 'down'>('checking')

  // The server is asked once when the screen opens, and again from the notice's button, which shows the check at once.
  const askServer = useCallback(() => {
    void call('health').then((answer) => setServer(answer.ok ? 'up' : 'down'))
  }, [call])
  useEffect(askServer, [askServer])
  function checkServer() {
    setServer('checking')
    askServer()
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    // A language chosen on this screen becomes the account's (H31).
    const result = await call<{ account: Account }>('login', { login, password, language: chosenLanguage() })
    setBusy(false)
    if (result.ok) signedIn(result.data.account)
    else {
      setError(errorText(result, t))
      setPassword('')
      if (result.error === 'server_unreachable') setServer('down')
    }
  }

  return (
    <main className="narrow">
      <LanguageSwitch />
      <h1>{t.appName}</h1>
      <p className="lead">{t.signInLead}</p>
      {notice && (
        <Notice role="status" still>
          {notice}
        </Notice>
      )}
      {server === 'down' && (
        <Notice tone="alert" role="alert">
          <p>
            {t.serverDown.before}
            <button type="button" className="link" onClick={checkServer}>
              {t.serverDown.action}
            </button>
            {t.serverDown.after}
          </p>
        </Notice>
      )}
      <form onSubmit={submit} noValidate>
        <Field label={t.login} value={login} onChange={setLogin} autoComplete="username" />
        <PasswordField label={t.password} value={password} onChange={setPassword} autoComplete="current-password" />
        {error && (
          <Notice tone="alert" role="alert">
            {error}
          </Notice>
        )}
        <button type="submit" className="primary" disabled={busy || !login || !password}>
          {busy ? t.signingIn : t.signIn}
        </button>
      </form>
      <p className="aside">
        <Link to="/forgot-password">{t.forgotPassword}</Link>
      </p>
      <p className="aside">
        {t.noAccount} <Link to="/register">{t.toRegister}</Link>
      </p>
    </main>
  )
}
