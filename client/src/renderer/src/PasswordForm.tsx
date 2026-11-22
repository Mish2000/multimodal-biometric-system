import { useState, type FormEvent } from 'react'
import type { Account } from '../../shared/bridge'
import { PasswordField } from './PasswordField'
import { useSession } from './session'
import { errorText } from './texts'
import { Notice } from './ui/Notice'

// The password's replacement, shared by the settings' security area (H28) and the one-time password's own
// screen (H12), with the strength meter on the new password (H30). The server signs the account's other
// sessions out when its password changes.
export function PasswordForm({ oneTime, onChanged }: { oneTime: boolean; onChanged: (account: Account) => void }) {
  const { call, t } = useSession()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setDone(false)
    if (next !== repeat) {
      setError(t.passwordsDiffer)
      return
    }
    setBusy(true)
    setError('')
    const changed = await call('changePassword', { current, new: next })
    if (!changed.ok) {
      setBusy(false)
      setError(errorText(changed, t))
      return
    }
    const me = await call<{ account: Account }>('me')
    setBusy(false)
    setCurrent('')
    setNext('')
    setRepeat('')
    if (me.ok) {
      if (!oneTime) setDone(true)
      onChanged(me.data.account)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <PasswordField
        label={oneTime ? t.oneTimePassword : t.currentPassword}
        value={current}
        onChange={setCurrent}
        autoComplete="current-password"
      />
      <PasswordField label={t.newPassword} value={next} onChange={setNext} autoComplete="new-password" meter />
      <PasswordField label={t.repeatPassword} value={repeat} onChange={setRepeat} autoComplete="new-password" />
      {error && (
        <Notice tone="alert" role="alert">
          {error}
        </Notice>
      )}
      {done && (
        <Notice tone="done" role="status">
          {t.passwordChanged}
        </Notice>
      )}
      <button type="submit" className="primary" disabled={busy || !current || !next || !repeat}>
        {busy ? t.saving : oneTime ? t.save : t.changePassword}
      </button>
    </form>
  )
}
