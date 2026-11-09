// H49: face verification (1:1). SFace's card, without a choice, and an explicit start (H40); then the camera
// panel of H48. An image that fails its checks is taken again and makes no attempt, at most twelve per run
// (as H35). The server compares a passing image with the three enrolled ones, saves the attempt with its sealed
// image, and only then answers; the result shows the new face beside the closest enrolled one.
import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { FaceCheck, FaceMethod, FaceVerificationAnswer, FaceVerificationResult } from '../../../shared/bridge'
import { errorText } from '../texts'
import { useSession } from '../session'
import { CameraPanel } from './CameraPanel'
import { checkLine, MOST_TAKEN } from './FaceEnrolment'

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
  const { call, t } = useSession()
  const f = t.face
  const v = f.verify
  const navigate = useNavigate()
  const [phase, setPhase] = useState<'card' | 'live' | 'checking' | 'failed'>('card')
  const [taken, setTaken] = useState(0)
  const [rejected, setRejected] = useState<FaceCheck[] | null>(null)
  const [result, setResult] = useState<FaceVerificationResult | null>(null)
  const [failure, setFailure] = useState('')

  if (!enrolled)
    return (
      <section>
        <h1>{v.title}</h1>
        <p className="notice" role="status">{v.notEnrolled}</p>
        <div className="actions">
          <button type="button" onClick={onEnrol}>{v.enrolNow}</button>
          <button type="button" className="secondary" onClick={() => navigate('/')}>{v.home}</button>
        </div>
      </section>
    )

  if (result !== null)
    return <FaceVerificationView result={result} onLeave={onLeave} onAgain={() => {
      setResult(null)
      setTaken(0)
      setRejected(null)
      setPhase('live')
    }} />

  async function check(image: string) {
    const count = taken + 1
    setTaken(count)
    setRejected(null)
    setPhase('checking')
    const answer = await call<FaceVerificationAnswer>('verifyFace', { image })
    if (!answer.ok) {
      setPhase('failed')
      setFailure(f.errors[answer.error] ?? errorText(answer, t))
      return
    }
    if (answer.data.status === 'verified') {
      setResult(answer.data)
      return
    }
    setRejected(answer.data.checks)
    if (count >= MOST_TAKEN) {
      setPhase('failed')
      setFailure(f.errors.too_many_images ?? t.unexpected)
    } else setPhase('live')
  }

  if (phase === 'card')
    return (
      <section className="method-selection">
        <h1>{v.title}</h1>
        <p className="lead">{v.lead}</p>
        <div className="setting method-card">
          <h2>SFace</h2>
          <p>{f.methodText}</p>
          <p className="aside">{f.methodThreshold(method.threshold)}</p>
          <p className="aside">{f.methodAccuracy}</p>
          <p className="aside">{v.speed}</p>
        </div>
        <div className="actions">
          <button type="button" disabled={!method.available} onClick={() => setPhase('live')}>{v.start}</button>
          <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
        </div>
      </section>
    )

  return (
    <section className="enrolment face-verification">
      <h1>{v.title}</h1>
      <p className="aside">{f.guide.noFace}</p>
      {phase === 'failed' ? (
        <>
          <p className="error" role="alert">{failure}</p>
          <div className="actions">
            <button type="button" onClick={() => {
              setTaken(0)
              setRejected(null)
              setPhase('live')
            }}>{f.tryAgain}</button>
            <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
          </div>
        </>
      ) : (
        <>
          <CameraPanel busy={phase !== 'live'} minimumWidth={method.width_minimum} onTaken={(image) => void check(image)} />
          <p className="notice prompt" role="status" aria-live="polite">{phase === 'checking' ? v.comparing : ''}</p>
          {rejected !== null && (
            <div className="rejected">
              <p>{f.rejected}</p>
              <ul className="checks">
                {rejected.map((item) => (
                  <li key={item.name} className={item.passed ? 'met' : 'missing'}>
                    <span className="mark" aria-hidden="true">{item.passed ? '✓' : '✗'}</span> {checkLine(item, t)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button type="button" className="secondary" onClick={onLeave}>{f.cancel}</button>
        </>
      )}
    </section>
  )
}
