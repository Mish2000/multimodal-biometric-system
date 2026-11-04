import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Field } from '../Field'
import { PasswordField, RevealInput } from '../PasswordField'
import { useSession } from '../session'
import { errorText, type Texts } from '../texts'

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

const when = (iso: string, t: Texts) =>
  new Date(iso).toLocaleString(t.dateLocale, { dateStyle: 'short', timeStyle: 'short' })

// The administration area of increment 1 (H12): accounts, new administrators, disabling, the audit log.
// Every change asks for the administrator's own password again.
export function Admin() {
  const { account, call, t } = useSession()
  const [accounts, setAccounts] = useState<AccountRow[] | null>(null)
  const [audit, setAudit] = useState<AuditRow[] | null>(null)
  const [error, setError] = useState<Parameters<typeof errorText>[0] | null>(null)

  const load = useCallback(async () => {
    const [list, log] = await Promise.all([
      call<{ accounts: AccountRow[] }>('accounts'),
      call<{ entries: AuditRow[] }>('audit'),
    ])
    if (list.ok) setAccounts(list.data.accounts)
    else setError(list)
    if (log.ok) setAudit(log.data.entries)
  }, [call])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section>
      <h1>{t.administration}</h1>
      {error && (
        <p className="error" role="alert">
          {errorText(error, t)}
        </p>
      )}
      <h2>{t.accounts}</h2>
      {accounts === null ? (
        <p className="aside">{t.loading}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t.username}</th>
              <th>{t.email}</th>
              <th>{t.role}</th>
              <th>{t.status}</th>
              <th>{t.created}</th>
              <th>{t.action}</th>
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
      <h2>{t.auditLog}</h2>
      {audit === null ? (
        <p className="aside">{t.loading}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t.when}</th>
              <th>{t.administrator}</th>
              <th>{t.action}</th>
              <th>{t.target}</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((entry, index) => (
              <tr key={index}>
                <td>{when(entry.at, t)}</td>
                <td>
                  <bdi>{entry.administrator}</bdi>
                </td>
                <td>{t.auditActions[entry.action] ?? entry.action}</td>
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
  const { call, t } = useSession()
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
    } else setError(errorText(result, t))
  }

  return (
    <tr>
      <td>
        <bdi>{row.username}</bdi>
      </td>
      <td dir="ltr">{row.email}</td>
      <td>{t.roles[row.role]}</td>
      <td>{t.statuses[row.status]}</td>
      <td>{when(row.created_at, t)}</td>
      <td>
        {self ? (
          <span className="aside">{t.yourAccount}</span>
        ) : asking ? (
          <form className="inline" onSubmit={apply} noValidate>
            <RevealInput
              label={t.confirmPassword}
              placeholder={t.yourPassword}
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
            />
            <button type="submit" disabled={!password}>
              {next === 'disabled' ? t.disable : t.enable}
            </button>
            <button type="button" className="link" onClick={() => setAsking(false)}>
              {t.cancel}
            </button>
            {error && (
              <span className="error" role="alert">
                {error}
              </span>
            )}
          </form>
        ) : (
          <button type="button" className="secondary" onClick={() => setAsking(true)}>
            {next === 'disabled' ? t.disableAsk : t.enableAsk}
          </button>
        )}
      </td>
    </tr>
  )
}

function NewAdministrator({ created }: { created(): Promise<void> }) {
  const { call, t } = useSession()
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
      setError(errorText(result, t))
      return
    }
    setOneTime({ username: result.data.account.username, password: result.data.one_time_password })
    setUsername('')
    setEmail('')
    await created()
  }

  return (
    <>
      <h2>{t.newAdministrator}</h2>
      {oneTime && (
        <p className="ok" role="status">
          {t.administratorCreated.before}
          <bdi>{oneTime.username}</bdi>
          {t.administratorCreated.middle}
          <code dir="ltr">{oneTime.password}</code>
          {t.administratorCreated.after}
        </p>
      )}
      <form className="row" onSubmit={submit} noValidate>
        <Field label={t.username} value={username} onChange={setUsername} autoComplete="off" />
        <Field label={t.email} type="email" value={email} onChange={setEmail} autoComplete="off" dir="ltr" />
        <PasswordField label={t.confirmPassword} value={password} onChange={setPassword} autoComplete="current-password" />
        <button type="submit" disabled={!username || !email || !password}>
          {t.create}
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
