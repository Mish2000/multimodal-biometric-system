import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Account } from '../../../shared/bridge'
import { Field } from '../Field'
import { landing, useSession } from '../session'
import { errorText } from '../texts'

export function ChangePassword() {
  const { account, call, update } = useSession()
  const navigate = useNavigate()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const oneTime = account?.must_change_password ?? false

  async function submit(event: FormEvent) {
    event.preventDefault()
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
      update(me.data.account)
      if (oneTime) navigate(landing(me.data.account), { replace: true })
      else setDone(true)
    }
  }

  return (
    <section className="narrow">
      <h1>{oneTime ? 'בחירת סיסמה חדשה' : 'החלפת סיסמה'}</h1>
      {oneTime && <p className="lead">החשבון נוצר עם סיסמה חד-פעמית. לפני שממשיכים, בוחרים סיסמה משלך.</p>}
      {done && (
        <p className="ok" role="status">
          הסיסמה הוחלפה. כניסות אחרות של החשבון הזה הסתיימו.
        </p>
      )}
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
        <button type="submit" disabled={busy || !current || !next || !repeat}>
          {busy ? 'שומרים…' : 'שמירה'}
        </button>
      </form>
    </section>
  )
}
