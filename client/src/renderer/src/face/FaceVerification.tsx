// H49: face verification (1:1). SFace's card, without a choice, and an explicit start (H40); then the camera
// panel of H48. An image that fails its checks is taken again and makes no attempt, at most twelve per run
// (as H35). The server compares a passing image with the three enrolled ones, saves the attempt with its sealed
// image, and only then answers; the result shows the new face beside the closest enrolled one.
import { useState } from 'react'
import type { FaceMethod, FaceVerificationResult } from '../../../shared/bridge'
import { useSession } from '../session'
import { FaceCard, FaceNotEnrolled, FaceTake } from './FaceTake'

export function FaceVerificationView({ result, onAgain, onLeave }: { result: FaceVerificationResult; onAgain: () => void; onLeave: () => void }) {
  const { t } = useSession()
  const v = t.face.verify
  return (
    <section className="face-verification-result">
      <h1>{result.accepted ? v.match : v.noMatch}</h1>
      <div className="face-pair" dir="ltr">
        <figure>
          <img src={`data:image/png;base64,${result.view.probe}`} alt={v.newImage} width={112} height={112} />
          <figcaption>{v.newImage}</figcaption>
        </figure>
        <figure>
          <img src={`data:image/png;base64,${result.view.reference}`} alt={v.enrolledImage(result.view.placement)} width={112} height={112} />
          <figcaption>{v.enrolledImage(result.view.placement)}</figcaption>
        </figure>
      </div>
      <p className="aside">{t.face.alignedNote}</p>
      <meter className="face-score" min={0} max={1} value={Math.max(0, result.score)} aria-label={v.scoreLabel} />
      <p className={result.accepted ? 'ok' : 'error'}>{v.score(result.score, result.threshold)}</p>
      <p className="aside">{v.time(result.duration_ms)} {v.saved}</p>
      <h2>{v.comparisonsTitle}</h2>
      <ul className="checks">
        {result.comparisons.map((comparison) => (
          <li key={comparison.placement} className={comparison.accepted ? 'met' : 'missing'}>
            <span className="mark" aria-hidden="true">{comparison.accepted ? '✓' : '✗'}</span>{' '}
            <strong>{v.enrolledImage(comparison.placement)}</strong>{' '}
            <bdi dir="ltr">{comparison.score.toFixed(3)}</bdi>{' '}
            <span className="aside">{comparison.accepted ? t.face.above : t.face.notAbove}</span>
          </li>
        ))}
      </ul>
      <div className="actions">
        <button type="button" onClick={onAgain}>{v.again}</button>
        <button type="button" className="secondary" onClick={onLeave}>{t.face.back}</button>
      </div>
    </section>
  )
}

export function FaceVerification({ method, enrolled, onEnrol, onLeave }: { method: FaceMethod; enrolled: boolean; onEnrol: () => void; onLeave: () => void }) {
  const { t } = useSession()
  const v = t.face.verify
  const [started, setStarted] = useState(false)
  const [run, setRun] = useState(0)
  const [result, setResult] = useState<FaceVerificationResult | null>(null)

  if (!enrolled) return <FaceNotEnrolled title={v.title} text={v.notEnrolled} onEnrol={onEnrol} />
  if (result !== null)
    return <FaceVerificationView result={result} onLeave={onLeave} onAgain={() => {
      setResult(null)
      setRun((value) => value + 1)
    }} />
  if (!started)
    return <FaceCard title={v.title} lead={v.lead} method={method} notes={[v.speed]} start={v.start}
      onStart={() => setStarted(true)} onLeave={onLeave} />
  return <FaceTake<FaceVerificationResult> key={run} title={v.title} route="verifyFace" minimumWidth={method.width_minimum}
    comparing={v.comparing} onResult={setResult} onLeave={onLeave} />
}
