import { useEffect, useState } from 'react'
import { useSession } from '../session'
import { MODALITY_NAMES } from '../texts'

type Modalities = Record<string, { enrolled: boolean }>

export function Home() {
  const { account, call } = useSession()
  const [modalities, setModalities] = useState<Modalities | null>(null)

  useEffect(() => {
    void call<{ modalities: Modalities | null }>('me').then((result) => {
      if (result.ok) setModalities(result.data.modalities ?? {})
    })
  }, [call])

  return (
    <section>
      <h1>
        שלום, <bdi>{account?.username}</bdi>
      </h1>
      <p className="lead">
        שלוש דרכי זיהוי. בכל אחת נרשמים פעם אחת, ואחר כך אפשר לאמת (<bdi dir="ltr">1:1</bdi>) ולזהות (
        <bdi dir="ltr">1:N</bdi>).
      </p>
      {modalities === null ? (
        <p className="aside">טוען…</p>
      ) : (
        <ul className="cards">
          {Object.entries(modalities).map(([modality, { enrolled }]) => (
            <li key={modality} className="card">
              <h2>{MODALITY_NAMES[modality] ?? modality}</h2>
              <p>{enrolled ? 'רשום' : 'עוד לא נרשם'}</p>
              <p className="aside">הרישום, האימות והזיהוי יתווספו בשלבי הבנייה הבאים.</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
