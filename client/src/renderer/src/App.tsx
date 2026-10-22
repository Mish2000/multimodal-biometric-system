import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import type { Account } from '../../shared/bridge'
import { Layout } from './Layout'
import { Admin } from './pages/Admin'
import { ChangePassword } from './pages/ChangePassword'
import { Home } from './pages/Home'
import { Register } from './pages/Register'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { landing, useSession } from './session'

// The navigation of the system (docs/specification.md, section 6): sign-in and registration before an
// account is signed in; then the home screen for users, the administration area for administrators, and
// the settings. An account with a one-time password goes nowhere until it is replaced (H12). The server
// checks every request again, whatever the page shows.
export function App() {
  const { account, ready } = useSession()
  if (!ready) return <p className="aside centered">טוען…</p>
  const home = landing(account)

  // An account sees a screen only when its role fits and its one-time password is gone.
  const only = (role: Account['role'] | 'any', screen: ReactElement): ReactElement => {
    if (account === null) return <Navigate to="/sign-in" replace />
    if (account.must_change_password || (role !== 'any' && account.role !== role)) return <Navigate to={home} replace />
    return screen
  }

  return (
    <Routes>
      <Route path="/sign-in" element={account ? <Navigate to={home} replace /> : <SignIn />} />
      <Route path="/register" element={account ? <Navigate to={home} replace /> : <Register />} />
      <Route element={account ? <Layout /> : <Navigate to="/sign-in" replace />}>
        <Route path="/" element={only('user', <Home />)} />
        <Route path="/admin" element={only('admin', <Admin />)} />
        <Route path="/settings" element={only('any', <Settings />)} />
        <Route path="/password" element={<ChangePassword />} />
      </Route>
      <Route path="*" element={<Navigate to={home} replace />} />
    </Routes>
  )
}
