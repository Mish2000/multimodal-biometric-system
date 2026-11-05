import { useEffect, useState, type ReactElement } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import type { Account, OpenedLink } from '../../shared/bridge'
import { Layout } from './Layout'
import { Admin } from './pages/Admin'
import { ChangePassword } from './pages/ChangePassword'
import { Fingerprint } from './pages/Fingerprint'
import { ForgotPassword } from './pages/ForgotPassword'
import { Home } from './pages/Home'
import { Register } from './pages/Register'
import { ResetPassword } from './pages/ResetPassword'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { landing, useSession } from './session'

// The navigation of the system (docs/specification.md, section 6): sign-in, registration and password
// recovery before an account is signed in (H32); then the home screen for users, the administration area for
// administrators, and the settings, where the password is changed too (H28). An account with a one-time
// password goes nowhere but its own replacement screen until it is replaced (H12). A reset link opens its
// screen whoever is signed in. The server checks every request again, whatever the page shows.
export function App() {
  const { account, ready, t } = useSession()
  const location = useLocation()
  useOpenedLinks()
  if (!ready) return <p className="aside centered">{t.loading}</p>
  const home = landing(account)

  // An account sees a screen only when its role fits and its one-time password is gone.
  const only = (role: Account['role'] | 'any', screen: ReactElement): ReactElement => {
    if (account === null) return <Navigate to="/sign-in" replace />
    if (account.must_change_password || (role !== 'any' && account.role !== role)) return <Navigate to={home} replace />
    return screen
  }
  const signedOut = (screen: ReactElement): ReactElement => (account ? <Navigate to={home} replace /> : screen)

  return (
    <Routes>
      <Route path="/sign-in" element={signedOut(<SignIn />)} />
      <Route path="/register" element={signedOut(<Register />)} />
      <Route path="/forgot-password" element={signedOut(<ForgotPassword />)} />
      {/* Each opened link checks its own token, so a newer link starts the screen afresh. */}
      <Route path="/reset-password" element={<ResetPassword key={location.key} />} />
      <Route element={account ? <Layout /> : <Navigate to="/sign-in" replace />}>
        <Route path="/" element={only('user', <Home />)} />
        <Route path="/fingerprint" element={only('user', <Fingerprint />)} />
        <Route path="/admin" element={only('admin', <Admin />)} />
        <Route path="/settings" element={only('any', <Settings />)} />
        <Route path="/password" element={account?.must_change_password ? <ChangePassword /> : <Navigate to={home} replace />} />
      </Route>
      <Route path="*" element={<Navigate to={home} replace />} />
    </Routes>
  )
}

// A link that opened the client (H32), when the page starts or while it runs: its screen opens, in the
// language of the message it came in.
function useOpenedLinks(): void {
  const navigate = useNavigate()
  const { chooseLanguage } = useSession()
  const [opened, setOpened] = useState<OpenedLink | null>(null)

  useEffect(() => {
    const take = () => {
      void window.mbs.takeLink().then((link) => {
        if (link !== null) setOpened(link)
      })
    }
    take()
    return window.mbs.onLink(take)
  }, [])

  useEffect(() => {
    if (opened === null) return
    if (opened.language !== null) chooseLanguage(opened.language, false)
    setOpened(null)
    navigate('/reset-password')
  }, [opened, chooseLanguage, navigate])
}
