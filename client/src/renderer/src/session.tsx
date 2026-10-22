// Who is signed in, as the page knows it. The session itself (its token) is kept by the main process.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Account, ApiResult, RouteName } from '../../shared/bridge'

interface SessionValue {
  account: Account | null
  ready: boolean
  notice: string
  call<T = unknown>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>>
  signedIn(account: Account): void
  update(account: Account): void
  signOut(): Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null)
  const [ready, setReady] = useState(false)
  const [notice, setNotice] = useState('')
  const current = useRef<Account | null>(null)
  current.current = account

  // Every request goes through here: a session that ended on the server sends the window back to sign-in.
  const call = useCallback(async <T,>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>> => {
    const result = await window.mbs.call<T>(route, body, id)
    if (!result.ok && result.error === 'not_signed_in' && current.current !== null) {
      setNotice('הכניסה הסתיימה. צריך להיכנס שוב.')
      setAccount(null)
    }
    return result
  }, [])

  // After a reload the main process may still hold the session.
  useEffect(() => {
    void window.mbs.call<{ account: Account }>('me').then((result) => {
      if (result.ok) setAccount(result.data.account)
      setReady(true)
    })
  }, [])

  // Before anyone signs in the window follows Windows' setting; after it, the account's choice (H24).
  // Nothing changes before the session is known, so a reload does not flash the other theme.
  const theme = account?.theme ?? 'system'
  useEffect(() => {
    if (ready) window.mbs.setTheme(theme)
  }, [ready, theme])

  const value = useMemo<SessionValue>(
    () => ({
      account,
      ready,
      notice,
      call,
      signedIn: (next) => {
        setNotice('')
        setAccount(next)
      },
      update: setAccount,
      signOut: async () => {
        await window.mbs.call('logout')
        setNotice('')
        setAccount(null)
      },
    }),
    [account, ready, notice, call],
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
