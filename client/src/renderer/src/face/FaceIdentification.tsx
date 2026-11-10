// H50: face identification (1:N). SFace's card, without a choice, and an explicit start (H40); then the camera
// panel of H48, as in verification. The server ranks every current face enrolment of the active users by its
// highest similarity, saves the attempt with its sealed image, and only then answers. Other users stay anonymous,
// without a picture or a name, and only the caller's own enrolled face is shown (H18). The search itself is one
// database query of a few milliseconds, so the pass over the gallery of the specification plays once, for about
// 0.6 s, when the answer arrives; the time shown stays the server's processing time, and with Windows' animation
// effects off the pass is skipped.
import { useEffect, useRef, useState } from 'react'
import type { FaceIdentificationResult, FaceMethod } from '../../../shared/bridge'
import { useSession } from '../session'
import { FaceCard, FaceNotEnrolled, FaceTake, SourceLine } from './FaceTake'

export const PASS_MS = 600
const CELLS = 12

function reducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function Title() {
  const { t } = useSession()
  return <>{t.face.identify.title} <bdi dir="ltr">(1:N)</bdi></>
}

export function FaceIdentificationView({ result, onAgain, onLeave }: { result: FaceIdentificationResult; onAgain: () => void; onLeave: () => void }) {
  const { t } = useSession()
  const f = t.face
  const n = f.identify
  const v = f.verify
  const [passing, setPassing] = useState(() => !reducedMotion())
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (!passing) {
      heading.current?.focus()
      return
    }
    const timer = window.setTimeout(() => setPassing(false), PASS_MS)
    return () => window.clearTimeout(timer)
  }, [passing])

  const gallery = <p>{n.gallery(result.enrolments, result.gallery_size)}</p>
  if (passing)
    return (
      <section className="face-identification">
        <h1><Title /></h1>
        <div className="gallery-progress" role="status">
          <p>{n.comparing}</p>
          <div className="gallery-sweep passing" aria-hidden="true">
            {Array.from({ length: CELLS }, (_, index) => <span key={index} style={{ animationDelay: `${index * 35}ms` }} />)}
          </div>
          {gallery}
        </div>
      </section>
    )

  const leader = result.candidates[0]
  return (
    <section className="face-identification">
      <h1 ref={heading} tabIndex={-1}>{result.accepted ? n.found : n.notFound}</h1>
      {result.accepted && leader && (
        <p><strong>{result.tied_leaders > 1 ? n.tie(result.tied_leaders) : leader.own ? n.you : n.otherUser}</strong></p>
      )}
      <meter className="face-score" min={0} max={1} value={Math.max(0, result.score)} aria-label={v.scoreLabel} />
      <p className={result.accepted ? 'ok' : 'error'}>{n.score(result.score, result.threshold)}</p>
      <div className="table-wrap">
        <table>
          <caption>{n.ranking(result.candidates.length, result.enrolments)}</caption>
          <thead><tr><th>{n.rank}</th><th>{n.candidate}</th><th>{v.scoreLabel}</th><th>{n.decision}</th></tr></thead>
          <tbody>{result.candidates.map((candidate) => (
            <tr key={candidate.rank} className={candidate.own ? 'own' : undefined}>
              <td>{candidate.rank}</td>
              <td>{candidate.own ? n.you : n.otherUser}</td>
              <td><bdi dir="ltr">{candidate.score.toFixed(3)}</bdi></td>
              <td>{candidate.accepted ? f.above : f.notAbove}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {result.view ? (
        <>
          <p>{n.shownBeside(result.view.rank)}</p>
          <div className="face-pair" dir="ltr">
            <figure>
              <img src={`data:image/png;base64,${result.view.probe}`} alt={v.newImage} width={112} height={112} />
              <figcaption>{v.newImage}</figcaption>
            </figure>
            <figure>
              <img src={`data:image/png;base64,${result.view.reference}`} alt={n.yourImage(result.view.placement)} width={112} height={112} />
              <figcaption>{n.yourImage(result.view.placement)}</figcaption>
            </figure>
          </div>
          <p className="aside">{f.alignedNote}</p>
        </>
      ) : (
        <p className="aside">{n.noView}</p>
      )}
      {gallery}
      <p className="aside">{n.privacy}</p>
      <p className="aside">{v.time(result.duration_ms)} {v.saved}</p>
      <SourceLine source={result.source} size={result.size} />
      <div className="actions">
        <button type="button" onClick={onAgain}>{n.again}</button>
        <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
      </div>
    </section>
  )
}

export function FaceIdentification({ method, enrolled, onEnrol, onLeave }: { method: FaceMethod; enrolled: boolean; onEnrol: () => void; onLeave: () => void }) {
  const { t } = useSession()
  const n = t.face.identify
  const [started, setStarted] = useState(false)
  const [run, setRun] = useState(0)
  const [result, setResult] = useState<FaceIdentificationResult | null>(null)

  if (!enrolled) return <FaceNotEnrolled title={<Title />} text={n.notEnrolled} onEnrol={onEnrol} />
  if (result !== null)
    return <FaceIdentificationView key={result.attempt_id} result={result} onLeave={onLeave} onAgain={() => {
      setResult(null)
      setRun((value) => value + 1)
    }} />
  if (!started)
    return <FaceCard title={<Title />} lead={n.lead} method={method} notes={[n.privacy, n.speed]} start={n.start}
      onStart={() => setStarted(true)} onLeave={onLeave} />
  return <FaceTake<FaceIdentificationResult> key={run} title={<Title />} route="identifyFace" minimumWidth={method.width_minimum}
    comparing={n.comparing} errors={n.errors} onResult={setResult} onLeave={onLeave} />
}
