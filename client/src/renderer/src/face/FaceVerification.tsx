// H49: face verification (1:1). H53: SFace's card is a choice between the camera and an existing image (H51); an
// image that fails its checks makes no attempt and ends on its own outcome screen. The server compares a passing
// image with the three enrolled ones, saves the attempt with its sealed image, and only then answers; the result
// shows the new face beside the closest enrolled one, and "Verify again" returns to the choice.
import { useState } from 'react'
import type { FaceMethod, FaceVerificationResult } from '../../../shared/bridge'
import { useSession } from '../session'
import { FaceChoice, FaceNotEnrolled, FaceTake, SourceLine } from './FaceTake'

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
      <SourceLine source={result.source} size={result.size} />
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
  const [stage, setStage] = useState<'choice' | 'live' | 'file'>('choice') // H53
  const [run, setRun] = useState(0)
  const [result, setResult] = useState<FaceVerificationResult | null>(null)
  const choice = () => {
    setResult(null)
    setStage('choice')
    setRun((value) => value + 1)
  }

  if (!enrolled) return <FaceNotEnrolled title={v.title} text={v.notEnrolled} onEnrol={onEnrol} />
  if (result !== null) return <FaceVerificationView result={result} onLeave={onLeave} onAgain={choice} />
  if (stage === 'choice')
    return <FaceChoice title={v.title} lead={v.lead} method={method} notes={[v.speed]} live={v.live}
      onLive={() => setStage('live')} onFile={() => setStage('file')} onLeave={onLeave} />
  return <FaceTake<FaceVerificationResult> key={run} mode={stage} title={v.title} route="verifyFace"
    minimumWidth={method.width_minimum} comparing={v.comparing} again={v.again} onResult={setResult} onChoice={choice}
    onLeave={onLeave} />
}
