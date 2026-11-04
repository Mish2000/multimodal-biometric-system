import { LANGUAGES } from '../../shared/bridge'
import { useSession } from './session'
import { TEXTS } from './texts'

// The language switch of the screens before sign-in (H31): each language named in itself, as large products
// show it. The choice is saved in the account at registration or sign-in.
export function LanguageSwitch() {
  const { language, chooseLanguage, t } = useSession()
  return (
    <div className="language-switch" role="group" aria-label={t.language}>
      {LANGUAGES.map((option) => (
        <button
          key={option}
          type="button"
          className={option === language ? 'current' : 'link'}
          lang={option}
          aria-pressed={option === language}
          onClick={() => chooseLanguage(option)}
        >
          {TEXTS[option].languageName}
        </button>
      ))}
    </div>
  )
}
