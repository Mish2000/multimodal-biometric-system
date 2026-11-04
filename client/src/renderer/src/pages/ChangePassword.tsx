import { PasswordForm } from '../PasswordForm'
import { useSession } from '../session'

// The one-time password's replacement (H12): an account created with one goes nowhere else until it is
// replaced; once it is, the route sends the account to its landing (App). Every other change of password
// is made in the settings (H28).
export function ChangePassword() {
  const { update, t } = useSession()

  return (
    <section className="narrow">
      <h1>{t.choosePassword}</h1>
      <p className="lead">{t.oneTimeLead}</p>
      <PasswordForm oneTime onChanged={update} />
    </section>
  )
}
