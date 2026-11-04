import { useState } from 'react'
import { LANGUAGES, type Language, type Theme } from '../../../shared/bridge'
import { PasswordForm } from '../PasswordForm'
import { useSession } from '../session'
import { errorText, TEXTS } from '../texts'

const THEME_CHOICES: Theme[] = ['light', 'dark', 'system']

// The account's settings, in three areas: the theme (H24), the language (H31) and, under security, the
// password (H28).
export function Settings() {
  const { account, call, update, t } = useSession()
  const [error, setError] = useState('')
  if (account === null) return null

  async function chooseTheme(theme: Theme) {
    if (account === null || theme === account.theme) return
    setError('')
    const result = await call('changeTheme', { theme })
    if (result.ok) update({ ...account, theme })
    else setError(errorText(result, t))
  }

  async function chooseLanguage(language: Language) {
    if (account === null || language === account.language) return
    setError('')
    const result = await call('changeLanguage', { language })
    if (result.ok) update({ ...account, language })
    else setError(errorText(result, t))
  }

  return (
    <section className="narrow">
      <h1>{t.settings}</h1>
      <section className="setting" aria-labelledby="setting-look">
        <h2 id="setting-look">{t.appearance}</h2>
        <fieldset className="choices" aria-labelledby="setting-look">
          {THEME_CHOICES.map((theme) => (
            <label key={theme}>
              <input type="radio" name="theme" checked={account.theme === theme} onChange={() => void chooseTheme(theme)} />
              {t.themes[theme]}
            </label>
          ))}
        </fieldset>
        <p className="aside">{t.appearanceNote}</p>
      </section>
      <section className="setting" aria-labelledby="setting-language">
        <h2 id="setting-language">{t.language}</h2>
        <fieldset className="choices" aria-labelledby="setting-language">
          {LANGUAGES.map((language) => (
            <label key={language} lang={language}>
              <input
                type="radio"
                name="language"
                checked={account.language === language}
                onChange={() => void chooseLanguage(language)}
              />
              {TEXTS[language].languageName}
            </label>
          ))}
        </fieldset>
        <p className="aside">{t.languageNote}</p>
      </section>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <section className="setting" aria-labelledby="setting-security">
        <h2 id="setting-security">{t.security}</h2>
        <p className="aside">{t.securityNote}</p>
        <PasswordForm oneTime={false} onChanged={update} />
      </section>
    </section>
  )
}
