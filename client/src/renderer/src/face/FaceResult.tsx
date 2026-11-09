// H48: the enrolled face, once, from the server's answer: the three kept faces as SFace sees them, how alike
// each pair is against the threshold, and what was stored. The page keeps it only while this screen is open.
import type { FaceSaved } from '../../../shared/bridge'
import { useSession } from '../session'
import { FacePairs } from './FaceEnrolment'

export function FaceResult({ saved, onDone }: { saved: FaceSaved; onDone: () => void }) {
  const { t } = useSession()
  const f = t.face
  const length = saved.templates[0]?.embedding_length ?? 0
  return (
    <section className="face-result">
      <h1>{f.savedTitle}</h1>
      <p className="lead">{f.savedLead(saved.threshold)}</p>
      {saved.enrolment.replaced_previous && <p className="aside">{f.replacedPrevious}</p>}
      <ul className="thumbs faces">
        {saved.samples.map((sample) => (
          <li key={sample.id}>
            <img src={`data:image/png;base64,${sample.aligned}`} alt={f.image(sample.placement)} width={112} height={112} />
            <span>{f.image(sample.placement)}</span>
          </li>
        ))}
      </ul>
      <p className="aside">{f.alignedNote}</p>
      <h2>{f.pairsTitle}</h2>
      <FacePairs pairs={saved.pairs} threshold={saved.threshold} />
      {saved.not_kept.length > 0 && <p className="aside">{f.notKept(saved.not_kept.join(', '))}</p>}
      <p>{f.stored(saved.samples.length, length)}</p>
      <div className="actions">
        <button type="button" onClick={onDone}>{f.done}</button>
      </div>
    </section>
  )
}
