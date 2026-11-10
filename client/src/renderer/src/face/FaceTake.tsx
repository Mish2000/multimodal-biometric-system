// H49, H50: the pieces that face verification and identification share. Before an enrolment, the message of H15;
// SFace's card, without a choice, and an explicit start (H40); then the camera panel of H48 for one image that
// the server compares. An image that fails its checks is taken again and makes no attempt, at most twelve per
// run (as H35); the server's answer is either such a rejection or the completed, saved result.
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import type { FaceCheck, FaceDetection, FaceMethod, RouteName } from '../../../shared/bridge'
import { errorText } from '../texts'
import { useSession } from '../session'
import { CameraPanel } from './CameraPanel'
import { checkLine, MOST_TAKEN } from './FaceEnrolment'

export function FaceNotEnrolled({ title, text, onEnrol }: { title: ReactNode; text: string; onEnrol: () => void }) {
  const { t } = useSession()
  const navigate = useNavigate()
  return (
    <section>
      <h1>{title}</h1>
      <p className="notice" role="status">{text}</p>
      <div className="actions">
        <button type="button" onClick={onEnrol}>{t.face.verify.enrolNow}</button>
        <button type="button" className="secondary" onClick={() => navigate('/')}>{t.face.verify.home}</button>
      </div>
    </section>
  )
}

export function FaceCard({ title, lead, method, notes, start, onStart, onLeave }: {
  title: ReactNode
  lead: string
  method: FaceMethod
  notes: string[]
  start: string
  onStart: () => void
  onLeave: () => void
}) {
  const { t } = useSession()
  const f = t.face
  return (
    <section className="method-selection">
      <h1>{title}</h1>
      <p className="lead">{lead}</p>
      <div className="setting method-card">
        <h2>SFace</h2>
        <p>{f.methodText}</p>
        <p className="aside">{f.methodThreshold(method.threshold)}</p>
        <p className="aside">{f.methodAccuracy}</p>
        {notes.map((note) => <p key={note} className="aside">{note}</p>)}
      </div>
      <div className="actions">
        <button type="button" disabled={!method.available} onClick={onStart}>{start}</button>
        <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
      </div>
    </section>
  )
}

type Rejected = { status: 'rejected'; checks: FaceCheck[] } & FaceDetection

export function FaceTake<T extends { status: string }>({ title, route, minimumWidth, comparing, errors, onResult, onLeave }: {
  title: ReactNode
  route: Extract<RouteName, 'verifyFace' | 'identifyFace'>
  minimumWidth: number
  comparing: string
  errors?: Record<string, string>
  onResult: (result: T) => void
  onLeave: () => void
}) {
  const { call, t } = useSession()
  const f = t.face
  const [phase, setPhase] = useState<'live' | 'checking' | 'failed'>('live')
  const [taken, setTaken] = useState(0)
  const [rejected, setRejected] = useState<FaceCheck[] | null>(null)
  const [failure, setFailure] = useState('')

  async function check(image: string) {
    const count = taken + 1
    setTaken(count)
    setRejected(null)
    setPhase('checking')
    const answer = await call<T | Rejected>(route, { image })
    if (!answer.ok) {
      setPhase('failed')
      setFailure(errors?.[answer.error] ?? f.errors[answer.error] ?? errorText(answer, t))
      return
    }
    if (answer.data.status !== 'rejected') {
      onResult(answer.data as T)
      return
    }
    setRejected((answer.data as Rejected).checks)
    if (count >= MOST_TAKEN) {
      setPhase('failed')
      setFailure(f.errors.too_many_images ?? t.unexpected)
    } else setPhase('live')
  }

  return (
    <section className="enrolment face-verification">
      <h1>{title}</h1>
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
          <CameraPanel busy={phase !== 'live'} minimumWidth={minimumWidth} onTaken={(image) => void check(image)} />
          <p className="notice prompt" role="status" aria-live="polite">{phase === 'checking' ? comparing : ''}</p>
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
