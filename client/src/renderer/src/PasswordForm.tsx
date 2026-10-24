import { useState, type FormEvent } from 'react'
import type { Account } from '../../shared/bridge'
import { Field } from './Field'
import { useSession } from './session'
import { errorText } from './texts'

// The password's replacement, shared by the settings' security area (H28) and the one-time password's own
// screen (H12). The server signs the account's other sessions out when its password changes.
export function PasswordForm({ oneTime, onChanged }: { oneTime: boolean; onChanged: (account: Account) => void }) {
  const { call } = useSession()
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
      setError('שתי הסיסמאות החדשות לא זהות.')
      return
    }
    setBusy(true)
    setError('')
    const changed = await call('changePassword', { current, new: next })
    if (!changed.ok) {
      setBusy(false)
      setError(errorText(changed))
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
      <Field
        label={oneTime ? 'הסיסמה החד-פעמית' : 'הסיסמה הנוכחית'}
        type="password"
        value={current}
        onChange={setCurrent}
        autoComplete="current-password"
        dir="ltr"
      />
      <Field
        label="סיסמה חדשה"
        type="password"
        value={next}
        onChange={setNext}
        autoComplete="new-password"
        dir="ltr"
        hint="לפחות 12 תווים."
      />
      <Field label="הסיסמה החדשה שוב" type="password" value={repeat} onChange={setRepeat} autoComplete="new-password" dir="ltr" />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="ok" role="status">
          הסיסמה הוחלפה. הכניסות האחרות לחשבון נותקו.
        </p>
      )}
      <button type="submit" disabled={busy || !current || !next || !repeat}>
        {busy ? 'שומרים…' : oneTime ? 'שמירה' : 'החלפת הסיסמה'}
      </button>
    </form>
  )
}
