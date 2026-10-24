import { useState } from 'react'
import type { Theme } from '../../../shared/bridge'
import { PasswordForm } from '../PasswordForm'
import { useSession } from '../session'
import { errorText } from '../texts'

const CHOICES: Array<[Theme, string]> = [
  ['light', 'בהיר'],
  ['dark', 'כהה'],
  ['system', 'לפי Windows'],
]

// The account's settings, in two areas: the theme (H24) and, under security, the password (H28).
export function Settings() {
  const { account, call, update } = useSession()
  const [error, setError] = useState('')
  if (account === null) return null

  async function choose(theme: Theme) {
    if (account === null || theme === account.theme) return
    setError('')
    const result = await call('changeTheme', { theme })
    if (result.ok) update({ ...account, theme })
    else setError(errorText(result))
  }

  return (
    <section className="narrow">
      <h1>הגדרות</h1>
      <section className="setting" aria-labelledby="setting-look">
        <h2 id="setting-look">מראה</h2>
        <fieldset className="choices" aria-labelledby="setting-look">
          {CHOICES.map(([theme, label]) => (
            <label key={theme}>
              <input type="radio" name="theme" checked={account.theme === theme} onChange={() => void choose(theme)} />
              {label}
            </label>
          ))}
        </fieldset>
        <p className="aside">הבחירה נשמרת בחשבון שלך. במסכי הכניסה וההרשמה המראה הוא לפי Windows.</p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>
      <section className="setting" aria-labelledby="setting-security">
        <h2 id="setting-security">אבטחה</h2>
        <p className="aside">החלפת הסיסמה מנתקת את הכניסות האחרות לחשבון.</p>
        <PasswordForm oneTime={false} onChanged={update} />
      </section>
    </section>
  )
}
