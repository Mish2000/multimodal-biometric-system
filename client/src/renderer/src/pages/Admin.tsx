import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Field } from '../Field'
import { useSession } from '../session'
import { AUDIT_ACTIONS, errorText } from '../texts'

interface AccountRow {
  id: string
  username: string
  email: string
  role: 'user' | 'admin'
  status: 'active' | 'disabled'
  created_at: string
}

interface AuditRow {
  at: string
  administrator: string
  action: string
  target: string
}

const when = (iso: string) => new Date(iso).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' })

// The administration area of increment 1 (H12): accounts, new administrators, disabling, the audit log.
// Every change asks for the administrator's own password again.
export function Admin() {
  const { account, call } = useSession()
  const [accounts, setAccounts] = useState<AccountRow[] | null>(null)
  const [audit, setAudit] = useState<AuditRow[] | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const [list, log] = await Promise.all([
      call<{ accounts: AccountRow[] }>('accounts'),
      call<{ entries: AuditRow[] }>('audit'),
    ])
    if (list.ok) setAccounts(list.data.accounts)
    else setError(errorText(list))
    if (log.ok) setAudit(log.data.entries)
  }, [call])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section>
      <h1>אזור הניהול</h1>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <h2>חשבונות</h2>
      {accounts === null ? (
        <p className="aside">טוען…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>שם משתמש</th>
              <th>אימייל</th>
              <th>תפקיד</th>
              <th>מצב</th>
              <th>נוצר</th>
              <th>פעולה</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((row) => (
              <AccountLine key={row.id} row={row} self={row.id === account?.id} changed={load} />
            ))}
          </tbody>
        </table>
      )}
      <NewAdministrator created={load} />
      <h2>יומן הביקורת</h2>
      {audit === null ? (
        <p className="aside">טוען…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>מתי</th>
              <th>מנהל</th>
              <th>פעולה</th>
              <th>על מה</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((entry, index) => (
              <tr key={index}>
                <td>{when(entry.at)}</td>
                <td>
                  <bdi>{entry.administrator}</bdi>
                </td>
                <td>{AUDIT_ACTIONS[entry.action] ?? entry.action}</td>
                <td>
                  <bdi>{entry.target}</bdi>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function AccountLine({ row, self, changed }: { row: AccountRow; self: boolean; changed(): Promise<void> }) {
  const { call } = useSession()
  const [asking, setAsking] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const next = row.status === 'active' ? 'disabled' : 'active'

  async function apply(event: FormEvent) {
    event.preventDefault()
    setError('')
    const result = await call('setStatus', { password, status: next }, row.id)
    setPassword('')
    if (result.ok) {
      setAsking(false)
      await changed()
    } else setError(errorText(result))
  }

  return (
    <tr>
      <td>
        <bdi>{row.username}</bdi>
      </td>
      <td dir="ltr">{row.email}</td>
      <td>{row.role === 'admin' ? 'מנהל' : 'משתמש'}</td>
      <td>{row.status === 'active' ? 'פעיל' : 'מושבת'}</td>
      <td>{when(row.created_at)}</td>
      <td>
        {self ? (
          <span className="aside">החשבון שלך</span>
        ) : asking ? (
          <form className="inline" onSubmit={apply} noValidate>
            <input
              type="password"
              dir="ltr"
              aria-label="הסיסמה שלך, לאישור"
              placeholder="הסיסמה שלך"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button type="submit" disabled={!password}>
              {next === 'disabled' ? 'השבתה' : 'הפעלה'}
            </button>
            <button type="button" className="link" onClick={() => setAsking(false)}>
              ביטול
            </button>
            {error && (
              <span className="error" role="alert">
                {error}
              </span>
            )}
          </form>
        ) : (
          <button type="button" className="secondary" onClick={() => setAsking(true)}>
            {next === 'disabled' ? 'השבתה…' : 'הפעלה…'}
          </button>
        )}
      </td>
    </tr>
  )
}

function NewAdministrator({ created }: { created(): Promise<void> }) {
  const { call } = useSession()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [oneTime, setOneTime] = useState<{ username: string; password: string } | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    const result = await call<{ account: { username: string }; one_time_password: string }>('newAdministrator', {
      password,
      username,
      email,
    })
    setPassword('')
    if (!result.ok) {
      setError(errorText(result))
      return
    }
    setOneTime({ username: result.data.account.username, password: result.data.one_time_password })
    setUsername('')
    setEmail('')
    await created()
  }

  return (
    <>
      <h2>מנהל חדש</h2>
      {oneTime && (
        <p className="ok" role="status">
          נוצר המנהל <bdi>{oneTime.username}</bdi>. הסיסמה החד-פעמית שלו, שמוצגת רק עכשיו:{' '}
          <code dir="ltr">{oneTime.password}</code>. בכניסה הראשונה הוא יבחר סיסמה משלו.
        </p>
      )}
      <form className="row" onSubmit={submit} noValidate>
        <Field label="שם משתמש" value={username} onChange={setUsername} autoComplete="off" />
        <Field label="אימייל" type="email" value={email} onChange={setEmail} autoComplete="off" dir="ltr" />
        <Field label="הסיסמה שלך, לאישור" type="password" value={password} onChange={setPassword} autoComplete="current-password" dir="ltr" />
        <button type="submit" disabled={!username || !email || !password}>
          יצירה
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  )
}
