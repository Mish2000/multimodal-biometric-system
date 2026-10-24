import { NavLink, Outlet, useNavigate } from 'react-router'
import { useSession } from './session'

// The frame of every screen after sign-in: where to go, who is signed in, and sign-out.
export function Layout() {
  const { account, signOut } = useSession()
  const navigate = useNavigate()
  if (account === null) return null

  async function leave() {
    await signOut()
    navigate('/sign-in', { replace: true })
  }

  return (
    <div className="shell">
      <header className="top">
        <strong className="brand">מערכת הזיהוי</strong>
        {!account.must_change_password && (
          <nav>
            {account.role === 'admin' ? <NavLink to="/admin">אזור הניהול</NavLink> : <NavLink to="/" end>מסך הבית</NavLink>}
            <NavLink to="/settings">הגדרות</NavLink>
          </nav>
        )}
        <span className="who">
          <bdi>{account.username}</bdi>
          {account.role === 'admin' ? ', מנהל' : ''}
        </span>
        <button type="button" className="link" onClick={() => void leave()}>
          יציאה
        </button>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  )
}
