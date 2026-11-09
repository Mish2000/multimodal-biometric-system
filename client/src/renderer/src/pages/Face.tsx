// The face screen (H15, H48): its enrolment state, SFace's card, and the enrolment from the camera; a new
// enrolment replaces the current one, and the enrolment can be deleted, as H34 does for a finger.
import { useCallback, useEffect, useState } from 'react'
import type { FaceMethod, FaceSaved } from '../../../shared/bridge'
import { FaceEnrolment } from '../face/FaceEnrolment'
import { FaceResult } from '../face/FaceResult'
import { errorText } from '../texts'
import { useSession } from '../session'

type FaceState = { enrolled: boolean; enrolled_at?: string }

export function Face() {
  const { call, t } = useSession()
  const f = t.face
  const [state, setState] = useState<FaceState | null>(null)
  const [method, setMethod] = useState<FaceMethod | null>(null)
  const [enrolling, setEnrolling] = useState(false)
  const [saved, setSaved] = useState<FaceSaved | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const load = useCallback(() => {
    void call<{ modalities: Record<string, FaceState> | null }>('me').then((answer) => {
      if (answer.ok) setState(answer.data.modalities?.face ?? { enrolled: false })
      else setMessage({ kind: 'error', text: errorText(answer, t) })
    })
    void call<FaceMethod>('faceMethod').then((answer) => {
      if (answer.ok) setMethod(answer.data)
      else setMessage({ kind: 'error', text: errorText(answer, t) })
    })
  }, [call, t])
  useEffect(load, [load])

  async function remove() {
    setDeleting(true)
    const answer = await call('deleteFace')
    setDeleting(false)
    setConfirming(false)
    if (answer.ok) setMessage({ kind: 'ok', text: f.deleted })
    else setMessage({ kind: 'error', text: f.errors[answer.error] ?? errorText(answer, t) })
    load()
  }

  if (saved !== null)
    return <FaceResult saved={saved} onDone={() => { setSaved(null); load() }} />
  if (enrolling && method !== null)
    return (
      <FaceEnrolment
        method={method}
        onSaved={(result) => {
          setEnrolling(false)
          setSaved(result)
        }}
        onLeave={() => {
          setEnrolling(false)
          load()
        }}
      />
    )

  const when = state?.enrolled_at
    ? new Date(state.enrolled_at).toLocaleString(t.dateLocale, { dateStyle: 'long', timeStyle: 'short' })
    : ''
  return (
    <section>
      <h1>{t.modalities.face}</h1>
      <p className="lead">{f.lead}</p>
      {state === null || method === null ? (
        message?.kind === 'error' ? (
          <>
            <p className="error" role="alert">{message.text}</p>
            <button type="button" onClick={load}>{f.tryAgain}</button>
          </>
        ) : (
          <p className="aside">{t.loading}</p>
        )
      ) : (
        <>
          <div className="setting">
            <p><strong>{state.enrolled ? f.enrolledOn(when) : f.notEnrolled}</strong></p>
            {!method.available && <p className="error" role="alert">{f.unavailable}</p>}
            {state.enrolled && <p className="aside">{f.replaces}</p>}
            {confirming ? (
              <div className="confirm" role="alertdialog" aria-label={f.deleteEnrolment}>
                <p>{f.deleteAsk}</p>
                <div className="actions">
                  <button type="button" className="danger" disabled={deleting} onClick={() => void remove()}>
                    {deleting ? f.deleting : f.deleteConfirm}
                  </button>
                  <button type="button" className="secondary" disabled={deleting} onClick={() => setConfirming(false)}>
                    {t.cancel}
                  </button>
                </div>
              </div>
            ) : (
              <div className="actions">
                <button type="button" disabled={!method.available} onClick={() => {
                  setMessage(null)
                  setEnrolling(true)
                }}>
                  {state.enrolled ? f.enrolAgain : f.enrol}
                </button>
                {state.enrolled && (
                  <button type="button" className="secondary" onClick={() => setConfirming(true)}>{f.deleteEnrolment}</button>
                )}
              </div>
            )}
            {message !== null && (
              <p className={message.kind} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>
            )}
          </div>
          <div className="setting method-card">
            <h2>SFace</h2>
            <p>{f.methodText}</p>
            <p className="aside">{f.methodThreshold(method.threshold)}</p>
            <p className="aside">{f.methodAccuracy}</p>
          </div>
          <p className="aside">{f.nextSteps}</p>
        </>
      )}
    </section>
  )
}
