// Who is signed in, as the page knows it, and the language of the screens (H31). The session itself (its
// token) is kept by the main process.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Account, ApiResult, Language, RouteName } from '../../shared/bridge'
import { TEXTS, type Texts } from './texts'

interface SessionValue {
  account: Account | null
  ready: boolean
  notice: string
  language: Language
  t: Texts
  call<T = unknown>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>>
  signedIn(account: Account): void
  update(account: Account): void
  signOut(): Promise<void>
  // The language switch of the screens before sign-in; `chosenLanguage` is what the sign-in sends. A link's
  // language only shows the screens in it (`picked` false), so the account keeps its own at sign-in.
  chooseLanguage(language: Language, picked?: boolean): void
  chosenLanguage(): Language | undefined
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null)
  const [ready, setReady] = useState(false)
  const [notice, setNotice] = useState<'' | 'ended'>('')
  // English until someone chooses otherwise (H31); after sign-out the screens stay in the last language.
  const [screenLanguage, setScreenLanguage] = useState<Language>('en')
  const picked = useRef(false)
  const current = useRef<Account | null>(null)
  current.current = account

  const enter = useCallback((next: Account) => {
    picked.current = false
    setScreenLanguage(next.language)
    setAccount(next)
  }, [])

  // Every request goes through here: a session that ended on the server sends the window back to sign-in.
  const call = useCallback(async <T,>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>> => {
    const result = await window.mbs.call<T>(route, body, id)
    if (!result.ok && result.error === 'not_signed_in' && current.current !== null) {
      setNotice('ended')
      setAccount(null)
    }
    return result
  }, [])

  // After a reload the main process may still hold the session.
  useEffect(() => {
    void window.mbs.call<{ account: Account }>('me').then((result) => {
      if (result.ok) enter(result.data.account)
      setReady(true)
    })
  }, [enter])

  // Before anyone signs in the window follows Windows' setting; after it, the account's choice (H24).
  // Nothing changes before the session is known, so a reload does not flash the other theme.
  const theme = account?.theme ?? 'system'
  useEffect(() => {
    if (ready) window.mbs.setTheme(theme)
  }, [ready, theme])

  // The account's language once signed in, the switch's before (H31): direction and title follow it.
  const language = account?.language ?? screenLanguage
  const t = TEXTS[language]
  useEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = language === 'he' ? 'rtl' : 'ltr'
    document.title = TEXTS[language].appName
  }, [language])

  const value = useMemo<SessionValue>(
    () => ({
      account,
      ready,
      notice: notice === 'ended' ? t.sessionEnded : '',
      language,
      t,
      call,
      signedIn: (next) => {
        setNotice('')
        enter(next)
      },
      update: (next) => {
        setScreenLanguage(next.language)
        setAccount(next)
      },
      signOut: async () => {
        await window.mbs.call('logout')
        setNotice('')
        setAccount(null)
      },
      chooseLanguage: (next, chosen = true) => {
        if (chosen) picked.current = true
        setScreenLanguage(next)
      },
      chosenLanguage: () => (picked.current ? screenLanguage : undefined),
    }),
    [account, ready, notice, language, t, call, enter, screenLanguage],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (value === null) throw new Error('useSession needs a SessionProvider')
  return value
}

// Where an account belongs: sign-in, the one-time password's replacement, the administration area or home.
export function landing(account: Account | null): string {
  if (account === null) return '/sign-in'
  if (account.must_change_password) return '/password'
  return account.role === 'admin' ? '/admin' : '/'
}
