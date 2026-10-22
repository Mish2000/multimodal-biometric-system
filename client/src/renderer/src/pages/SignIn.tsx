import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { Account } from '../../../shared/bridge'
import { Field } from '../Field'
import { useSession } from '../session'
import { errorText } from '../texts'

export function SignIn() {
  const { call, signedIn, notice } = useSession()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [server, setServer] = useState<'checking' | 'up' | 'down'>('checking')

  async function checkServer() {
    setServer('checking')
    setServer((await call('health')).ok ? 'up' : 'down')
  }

  useEffect(() => {
    void checkServer()
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    const result = await call<{ account: Account }>('login', { login, password })
    setBusy(false)
    if (result.ok) signedIn(result.data.account)
    else {
      setError(errorText(result))
      setPassword('')
      if (result.error === 'server_unreachable') setServer('down')
    }
  }

  return (
    <main className="narrow">
      <h1>מערכת הזיהוי</h1>
      <p className="lead">כניסה עם שם משתמש או אימייל.</p>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {server === 'down' && (
        <p className="error" role="alert">
          השרת לא פועל. צריך להפעיל אותו, ואז{' '}
          <button type="button" className="link" onClick={() => void checkServer()}>
            לבדוק שוב
          </button>
          .
        </p>
      )}
      <form onSubmit={submit} noValidate>
        <Field label="שם משתמש או אימייל" value={login} onChange={setLogin} autoComplete="username" />
        <Field label="סיסמה" type="password" value={password} onChange={setPassword} autoComplete="current-password" dir="ltr" />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !login || !password}>
          {busy ? 'נכנסים…' : 'כניסה'}
        </button>
      </form>
      <p className="aside">
        אין לך חשבון? <Link to="/register">להרשמה</Link>
      </p>
    </main>
  )
}
