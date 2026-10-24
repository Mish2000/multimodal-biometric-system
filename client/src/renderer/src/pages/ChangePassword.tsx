import { PasswordForm } from '../PasswordForm'
import { useSession } from '../session'

// The one-time password's replacement (H12): an account created with one goes nowhere else until it is
// replaced; once it is, the route sends the account to its landing (App). Every other change of password
// is made in the settings (H28).
export function ChangePassword() {
  const { update } = useSession()

  return (
    <section className="narrow">
      <h1>בחירת סיסמה חדשה</h1>
      <p className="lead">החשבון נוצר עם סיסמה חד-פעמית. לפני שממשיכים, בוחרים סיסמה משלך.</p>
      <PasswordForm oneTime onChanged={update} />
    </section>
  )
}
