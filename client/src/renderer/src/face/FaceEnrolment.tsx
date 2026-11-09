// H48: the face's enrolment. The page takes the images; every taken image is checked by the server at once,
// and once three have passed, they are sent together. The server keeps the face when three of them match each
// other above SFace's threshold; otherwise the user takes another, up to six kept images or twelve taken.
import { useState } from 'react'
import type { ApiResult, FaceCheck, FaceCheckResult, FaceEnrolmentAnswer, FaceMethod, FacePair, FaceSaved } from '../../../shared/bridge'
import { errorText, type Texts } from '../texts'
import { useSession } from '../session'
import { CameraPanel } from './CameraPanel'

export const MOST_TAKEN = 12 // images taken in one enrolment, kept or not (as H33's captures)

export interface KeptImage {
  number: number // in the order kept, from 1, as the server numbers them
  image: string
  capturedAt: string
  aligned: string
}

type Shown = { kind: 'rejected'; checks: FaceCheck[] } | { kind: 'kept'; number: number } | { kind: 'another' } | null

export function checkLine(check: FaceCheck, t: Texts): string {
  const f = t.face
  const name = f.checks[check.name] ?? check.name
  if (check.name === 'one_face') return `${name}: ${f.found(check.count ?? 0)}`
  if (check.name === 'detector_score') return `${name}: ${f.scoreDetail(check.score ?? 0, check.minimum ?? 0)}`
  if (check.name === 'face_size') return `${name}: ${f.widthDetail(check.width ?? 0, check.minimum ?? 0)}`
  return check.passed ? name : `${name}: ${f.outsideDetail}`
}

export function FacePairs({ pairs, threshold }: { pairs: FacePair[]; threshold: number }) {
  const { t } = useSession()
  const f = t.face
  return (
    <ul className="checks">
      {pairs.map((pair) => (
        <li key={`${pair.reference}-${pair.probe}`} className={pair.accepted ? 'met' : 'missing'}>
          <span className="mark" aria-hidden="true">
            {pair.accepted ? '✓' : '✗'}
          </span>
          <strong>{f.pair(pair.probe, pair.reference)}</strong>{' '}
          <bdi dir="ltr">{pair.score.toFixed(3)}</bdi>{' '}
          <span className="aside">
            {pair.accepted ? f.above : f.notAbove} (<bdi dir="ltr">{threshold}</bdi>)
          </span>
        </li>
      ))}
    </ul>
  )
}

export function FaceEnrolment({ method, onSaved, onLeave }: { method: FaceMethod; onSaved: (saved: FaceSaved) => void; onLeave: () => void }) {
  const { call, t } = useSession()
  const f = t.face
  const [kept, setKept] = useState<KeptImage[]>([])
  const [taken, setTaken] = useState(0)
  const [phase, setPhase] = useState<'live' | 'checking' | 'saving' | 'failed'>('live')
  const [shown, setShown] = useState<Shown>(null)
  const [pairs, setPairs] = useState<FacePair[]>([])
  const [failure, setFailure] = useState('')

  function fail(code: string, result?: ApiResult) {
    setPhase('failed')
    setFailure(f.errors[code] ?? (result ? errorText(result, t) : t.unexpected))
  }

  function next(count: number) {
    if (count >= MOST_TAKEN) fail('too_many_images')
    else setPhase('live')
  }

  async function check(image: string, capturedAt: string) {
    const count = taken + 1
    setTaken(count)
    setPhase('checking')
    const answer = await call<FaceCheckResult>('checkFace', { image })
    if (!answer.ok) return fail(answer.error, answer)
    if (!answer.data.passed || answer.data.aligned === null) {
      setShown({ kind: 'rejected', checks: answer.data.checks })
      return next(count)
    }
    const now = [...kept, { number: kept.length + 1, image, capturedAt, aligned: answer.data.aligned }]
    setKept(now)
    setShown({ kind: 'kept', number: now.length })
    if (now.length < method.images) return next(count)
    setPhase('saving')
    const enrolled = await call<FaceEnrolmentAnswer>('enrolFace', {
      images: now.map((item) => ({ image: item.image, captured_at: item.capturedAt })),
    })
    if (!enrolled.ok) return fail(enrolled.error, enrolled)
    if (enrolled.data.status === 'saved') return onSaved(enrolled.data)
    setPairs(enrolled.data.pairs)
    if (enrolled.data.status === 'failed') return fail(enrolled.data.error)
    setShown({ kind: 'another' })
    next(count)
  }

  const restart = () => {
    setKept([])
    setTaken(0)
    setPairs([])
    setShown(null)
    setFailure('')
    setPhase('live')
  }

  return (
    <section className="enrolment face-enrolment">
      <h1>{f.enrolling}</h1>
      <p className="lead">{f.imageOf(Math.min(kept.length + 1, method.most_kept), Math.max(method.images, Math.min(kept.length + 1, method.most_kept)))}</p>
      <p className="aside">{f.between}</p>
      <ol className="placements" aria-label={f.keptTitle}>
        {Array.from({ length: Math.max(method.images, kept.length) }, (_, i) => (
          <li key={i} className={i < kept.length ? 'kept' : i === kept.length ? 'now' : ''} />
        ))}
      </ol>
      {phase === 'failed' ? (
        <>
          <p className="error" role="alert">{failure}</p>
          <div className="actions">
            <button type="button" onClick={restart}>{f.tryAgain}</button>
            <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
          </div>
        </>
      ) : (
        <>
          <CameraPanel busy={phase !== 'live'} minimumWidth={method.width_minimum}
            onTaken={(image, capturedAt) => void check(image, capturedAt)} />
          <p className="notice prompt" role="status" aria-live="polite">
            {phase === 'checking' ? f.checking : phase === 'saving' ? f.saving : shown?.kind === 'kept' ? f.kept(shown.number) : shown?.kind === 'another' ? f.another : ''}
          </p>
          {shown?.kind === 'rejected' && (
            <div className="rejected">
              <p>{f.rejected}</p>
              <ul className="checks">
                {shown.checks.map((item) => (
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
      {kept.length > 0 && (
        <>
          <h2>{f.keptTitle}</h2>
          <ul className="thumbs faces">
            {kept.map((item) => (
              <li key={item.number}>
                <img src={`data:image/png;base64,${item.aligned}`} alt="" width={112} height={112} />
                <span>{f.image(item.number)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {pairs.length > 0 && (
        <>
          <h2>{f.pairsTitle}</h2>
          <FacePairs pairs={pairs} threshold={method.threshold} />
        </>
      )}
    </section>
  )
}
