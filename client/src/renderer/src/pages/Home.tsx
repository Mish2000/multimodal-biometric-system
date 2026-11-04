import { useEffect, useState } from 'react'
import { useSession } from '../session'

type Modalities = Record<string, { enrolled: boolean }>

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
          {Object.entries(modalities).map(([modality, { enrolled }]) => (
            <li key={modality} className="card">
              <h2>{t.modalities[modality] ?? modality}</h2>
              <p>{enrolled ? t.enrolled : t.notEnrolled}</p>
              <p className="aside">{t.comingNext}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
