import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { useSession } from '../session'

type Modalities = Record<string, { enrolled: boolean; fingers?: number[] }>

// The modality cards (H15): the fingerprint opens its screen (H33); face and voice come in later steps.
export function Home() {
  const { account, call, t } = useSession()
  const [modalities, setModalities] = useState<Modalities | null>(null)

  useEffect(() => {
    void call<{ modalities: Modalities | null }>('me').then((result) => {
      if (result.ok) setModalities(result.data.modalities ?? {})
    })
  }, [call])

  return (
    <section>
      <h1>
        {t.hello}
        <bdi>{account?.username}</bdi>
      </h1>
      <p className="lead">
        {t.homeLead.before}
        <bdi dir="ltr">1:1</bdi>
        {t.homeLead.middle}
        <bdi dir="ltr">1:N</bdi>
        {t.homeLead.after}
      </p>
      {modalities === null ? (
        <p className="aside">{t.loading}</p>
      ) : (
        <ul className="cards">
          {Object.entries(modalities).map(([modality, { enrolled, fingers }]) => (
            <li key={modality} className="card">
              <h2>{t.modalities[modality] ?? modality}</h2>
              <p>{enrolled ? t.enrolled : t.notEnrolled}</p>
              {modality === 'fingerprint' ? (
                <>
                  {fingers && fingers.length > 0 && (
                    <p className="aside">
                      {t.fingerprint.enrolledFingers}
                      {fingers.map((finger) => t.fingerprint.fingers[finger]).join(', ')}
                    </p>
                  )}
                  <Link className="button" to="/fingerprint">
                    {t.fingerprint.open}
                  </Link>
                </>
              ) : (
                <p className="aside">{t.comingNext}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
