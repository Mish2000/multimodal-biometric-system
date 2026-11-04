import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { Field } from '../Field'
import { useSession } from '../session'
import { errorText } from '../texts'

type Channel = 'sms' | 'email'

// Password recovery while signed out (H32): a link by SMS to the registered mobile phone or by email. The
// answer is the same whether the details belong to an account or not, so the screen cannot tell either.
export function ForgotPassword() {
  const { call, t, language } = useSession()
  const [channel, setChannel] = useState<Channel>('sms')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<Channel | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const destination = channel === 'sms' ? phone : email

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setSent(null)
    const result = await call('requestReset', { channel, destination, language })
    setBusy(false)
    if (result.ok) setSent(channel)
    else setError(errorText(result, t))
  }

  function pick(next: Channel) {
    setChannel(next)
    setSent(null)
    setError('')
  }

  return (
    <main className="narrow">
      <h1>{t.resetTitle}</h1>
      <p className="lead">{t.resetLead}</p>
      <form onSubmit={submit} noValidate>
        <fieldset className="choices">
          <legend className="visually-hidden">{t.resetLead}</legend>
          <label>
            <input type="radio" name="channel" checked={channel === 'sms'} onChange={() => pick('sms')} />
            {t.bySms}
          </label>
          <label>
            <input type="radio" name="channel" checked={channel === 'email'} onChange={() => pick('email')} />
            {t.byEmail}
          </label>
        </fieldset>
        {channel === 'sms' ? (
          <Field
            label={t.phone}
            type="tel"
            value={phone}
            onChange={setPhone}
            autoComplete="tel"
            dir="ltr"
            inputMode="tel"
            hint={t.resetPhoneHint}
          />
        ) : (
          <Field
            label={t.email}
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            dir="ltr"
            hint={t.resetEmailHint}
          />
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {sent && (
          <p className="ok" role="status">
            {sent === 'sms' ? t.sentBySms : t.sentByEmail}
          </p>
        )}
        <button type="submit" disabled={busy || !destination}>
          {busy ? t.sending : t.sendLink}
        </button>
      </form>
      <p className="aside">
        <Link to="/sign-in">{t.backToSignIn}</Link>
      </p>
    </main>
  )
}
