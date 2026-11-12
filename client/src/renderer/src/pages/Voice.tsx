// The voice screen (H15, H54): its enrolment state, ECAPA-TDNN's card, and the enrolment from the microphone; a
// new enrolment replaces the current one, and the enrolment can be deleted, as H34 does for a finger and H48 for
// the face. Verification (1:1, H55) starts from here; identification (1:N) is the next step of increment 5.
import { useCallback, useEffect, useState } from 'react'
import type { VoiceMethod, VoiceSaved } from '../../../shared/bridge'
import { VoiceEnrolment, type KeptRecording } from '../voice/VoiceEnrolment'
import { VoiceResult } from '../voice/VoiceResult'
import { VoiceVerification } from '../voice/VoiceVerification'
import { errorText } from '../texts'
import { useSession } from '../session'

type VoiceState = { enrolled: boolean; enrolled_at?: string }

export function Voice() {
  const { call, t } = useSession()
  const v = t.voice
  const [state, setState] = useState<VoiceState | null>(null)
  const [method, setMethod] = useState<VoiceMethod | null>(null)
  const [enrolling, setEnrolling] = useState(false)
  const [verifying, setVerifying] = useState(false) // H55
  const [saved, setSaved] = useState<{ saved: VoiceSaved; kept: KeptRecording[] } | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const load = useCallback(() => {
    void call<{ modalities: Record<string, VoiceState> | null }>('me').then((answer) => {
      if (answer.ok) setState(answer.data.modalities?.voice ?? { enrolled: false })
      else setMessage({ kind: 'error', text: errorText(answer, t) })
    })
    void call<VoiceMethod>('voiceMethod').then((answer) => {
      if (answer.ok) setMethod(answer.data)
      else setMessage({ kind: 'error', text: errorText(answer, t) })
    })
  }, [call, t])
  useEffect(load, [load])

  async function remove() {
    setDeleting(true)
    const answer = await call('deleteVoice')
    setDeleting(false)
    setConfirming(false)
    if (answer.ok) setMessage({ kind: 'ok', text: v.deleted })
    else setMessage({ kind: 'error', text: v.errors[answer.error] ?? errorText(answer, t) })
    load()
  }

  if (saved !== null && method !== null)
    return <VoiceResult saved={saved.saved} kept={saved.kept} rate={method.sample_rate} onDone={() => { setSaved(null); load() }} />
  if (verifying && method !== null && state !== null)
    return (
      <VoiceVerification
        method={method}
        enrolled={state.enrolled}
        onEnrol={() => {
          setVerifying(false)
          setEnrolling(true)
        }}
        onLeave={() => {
          setVerifying(false)
          load()
        }}
      />
    )
  if (enrolling && method !== null)
    return (
      <VoiceEnrolment
        method={method}
        onSaved={(result, kept) => {
          setEnrolling(false)
          setSaved({ saved: result, kept })
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
      <h1>{t.modalities.voice}</h1>
      <p className="lead">{v.lead}</p>
      {state === null || method === null ? (
        message?.kind === 'error' ? (
          <>
            <p className="error" role="alert">{message.text}</p>
            <button type="button" onClick={load}>{v.tryAgain}</button>
          </>
        ) : (
          <p className="aside">{t.loading}</p>
        )
      ) : (
        <>
          <div className="setting">
            <p><strong>{state.enrolled ? v.enrolledOn(when) : v.notEnrolled}</strong></p>
            {!method.available && <p className="error" role="alert">{v.unavailable}</p>}
            {state.enrolled && <p className="aside">{v.replaces}</p>}
            {confirming ? (
              <div className="confirm" role="alertdialog" aria-label={v.deleteEnrolment}>
                <p>{v.deleteAsk}</p>
                <div className="actions">
                  <button type="button" className="danger" disabled={deleting} onClick={() => void remove()}>
                    {deleting ? v.deleting : v.deleteConfirm}
                  </button>
                  <button type="button" className="secondary" disabled={deleting} onClick={() => setConfirming(false)}>
                    {t.cancel}
                  </button>
                </div>
              </div>
            ) : (
              <div className="actions">
                {state.enrolled && (
                  <button type="button" disabled={!method.available} onClick={() => {
                    setMessage(null)
                    setVerifying(true)
                  }}>{v.verify.open}</button>
                )}
                <button type="button" className={state.enrolled ? 'secondary' : ''} disabled={!method.available} onClick={() => {
                  setMessage(null)
                  setEnrolling(true)
                }}>
                  {state.enrolled ? v.enrolAgain : v.enrol}
                </button>
                {!state.enrolled && (
                  <button type="button" className="secondary" disabled={!method.available} onClick={() => {
                    setMessage(null)
                    setVerifying(true)
                  }}>{v.verify.open}</button>
                )}
                {state.enrolled && (
                  <button type="button" className="secondary" onClick={() => setConfirming(true)}>{v.deleteEnrolment}</button>
                )}
              </div>
            )}
            {message !== null && (
              <p className={message.kind} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>
            )}
          </div>
          <div className="setting method-card">
            <h2>ECAPA-TDNN</h2>
            <p>{v.methodText}</p>
            <p className="aside">{v.methodThreshold(method.threshold)}</p>
            <p className="aside">{v.methodAccuracy}</p>
          </div>
          <p className="aside">{v.nextSteps}</p>
        </>
      )}
    </section>
  )
}
