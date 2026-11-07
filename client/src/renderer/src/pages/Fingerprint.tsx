// The fingerprint screen (H15, H33): choose a finger, enrol it from the scanner with live guidance, then see
// how its template is stored, or verify it with a new capture (H35).
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Check, EnrolmentEvent, Pair, SavedEnrolment, FingerprintAlgorithm, FingerprintMethod } from '../../../shared/bridge'
import { Checks, Journey, Pairs, type Captured } from '../fingerprint/Journey'
import { Verification } from '../fingerprint/Verification'
import { Identification } from '../fingerprint/Identification'
import { errorText, type Texts } from '../texts'
import { useSession } from '../session'

type FingerprintState = { enrolled: boolean; fingers?: number[] }

const HANDS: Array<{ hand: 'right' | 'left'; fingers: number[] }> = [
  { hand: 'right', fingers: [1, 2, 3, 4, 5] },
  { hand: 'left', fingers: [6, 7, 8, 9, 10] },
]

export function Fingerprint() {
  const { call, t } = useSession()
  const f = t.fingerprint
  const [enrolled, setEnrolled] = useState<number[] | null>(null)
  const [chosen, setChosen] = useState<number | null>(null)
  const [running, setRunning] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [identifying, setIdentifying] = useState(false)
  const [choosingMethod, setChoosingMethod] = useState(false)
  const methodHeading = useRef<HTMLHeadingElement>(null)
  const [methods, setMethods] = useState<FingerprintMethod[]>([])
  const [methodError, setMethodError] = useState('')
  const [algorithm, setAlgorithm] = useState<FingerprintAlgorithm>('opencv-sift')
  const [result, setResult] = useState<{ saved: SavedEnrolment; captures: Record<number, Captured> } | null>(null)
  // H34: deleting the chosen finger's enrolment, after a confirmation.
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  function choose(position: number) {
    setChosen(position)
    setConfirming(false)
    setMessage(null)
  }

  async function remove(position: number) {
    setDeleting(true)
    const answer = await call('deleteFingerprint', undefined, String(position))
    setDeleting(false)
    setConfirming(false)
    if (answer.ok) setMessage({ kind: 'ok', text: f.deleted(f.fingers[position] ?? '') })
    else setMessage({ kind: 'error', text: f.errors[answer.error] ?? errorText(answer, t) })
    load()
  }

  const load = useCallback(() => {
    void call<{ modalities: Record<string, FingerprintState> | null }>('me').then((answer) => {
      if (answer.ok) setEnrolled(answer.data.modalities?.fingerprint?.fingers ?? [])
      else setMessage({ kind: 'error', text: errorText(answer, t) })
    })
  }, [call, t])
  useEffect(load, [load])
  const loadMethods = useCallback(() => {
    setMethodError('')
    void call<{ methods: FingerprintMethod[] }>('fingerprintMethods').then((answer) => {
      if (answer.ok) setMethods(answer.data.methods)
      else setMethodError(errorText(answer, t))
    })
  }, [call, t])
  useEffect(loadMethods, [loadMethods])
  const selectedMethod = methods.find((method) => method.code === algorithm)
  useEffect(() => { if (choosingMethod) methodHeading.current?.focus() }, [choosingMethod])

  if (identifying)
    return <Identification enrolled={(enrolled?.length ?? 0) > 0} onLeave={() => {
      setIdentifying(false)
      load()
    }} />

  if (choosingMethod && chosen !== null)
    return (
      <section className="method-selection">
        <h1 ref={methodHeading} tabIndex={-1}>{f.verification.title}</h1>
        <p className="lead"><bdi>{f.fingers[chosen]}</bdi></p>
        <p>{f.methodLead}</p>
        <fieldset className="method-choices">
          <legend>{f.methodChoice}</legend>
          {methods.map((method) => (
            <label key={method.code} className="method-choice">
              <input type="radio" name="fingerprint-method" value={method.code} checked={algorithm === method.code}
                aria-labelledby={`method-${method.code}`} aria-describedby={`method-${method.code}-description`}
                disabled={!method.available} onChange={() => setAlgorithm(method.code)} />
              <span>
                <strong id={`method-${method.code}`}>{f.methodNames[method.code]}</strong>
                <span className="method-description" id={`method-${method.code}-description`}>{f.methodDescriptions[method.code]}</span>
                <span className="method-description aside">{f.methodAccuracy[method.code]}</span>
                <span className="method-description aside">{f.methodSpeed[method.code]}</span>
                <span className="method-description">{f.verification.threshold(method.threshold)}{method.threshold_provisional ? ` · ${f.provisional}` : ''}</span>
                {!method.available && <span className="method-description error">{f.methodUnavailable}</span>}
              </span>
            </label>
          ))}
          {methodError ? (
            <div>
              <p className="error" role="alert">{methodError}</p>
              <button type="button" className="secondary" onClick={loadMethods}>{f.tryAgain}</button>
            </div>
          ) : methods.length === 0 && <p className="aside">{t.loading}</p>}
        </fieldset>
        <div className="actions">
          <button type="button" disabled={!selectedMethod?.available} onClick={() => {
            setChoosingMethod(false)
            setVerifying(true)
          }}>{f.verification.begin}</button>
          <button type="button" className="secondary" onClick={() => setChoosingMethod(false)}>{f.back}</button>
        </div>
      </section>
    )

  if (verifying && chosen !== null)
    return (
      <Verification
        finger={chosen}
        enrolled={enrolled?.includes(chosen) ?? false}
        algorithm={algorithm}
        onChangeMethod={() => {
          // H40: retain the chosen finger and wait for an explicit start with the next method.
          setVerifying(false)
          setChoosingMethod(true)
          loadMethods()
        }}
        onLeave={() => {
          setVerifying(false)
          load()
        }}
        onEnrol={() => {
          setVerifying(false)
          setRunning(true)
        }}
      />
    )

  if (result !== null && chosen !== null)
    return (
      <Journey
        saved={result.saved}
        captures={result.captures}
        finger={chosen}
        onDone={() => {
          setResult(null)
          load()
        }}
      />
    )
  if (running && chosen !== null)
    return (
      <Enrolment
        finger={chosen}
        onSaved={(saved, captures) => {
          setRunning(false)
          setResult({ saved, captures })
        }}
        onLeave={() => {
          setRunning(false)
          load()
        }}
      />
    )

  return (
    <section>
      <h1>{t.modalities.fingerprint}</h1>
      <p className="lead">{f.lead}</p>
      {enrolled === null ? (
        message?.kind === 'error' ? (
          <>
            <p className="error" role="alert">{message.text}</p>
            <button type="button" onClick={load}>{f.tryAgain}</button>
          </>
        ) : <p className="aside">{t.loading}</p>
      ) : (
        <>
          <div className="hands">
            {HANDS.map(({ hand, fingers }) => (
              <fieldset key={hand} className="hand">
                <legend>{f.hands[hand]}</legend>
                {fingers.map((position) => (
                  <button
                    key={position}
                    type="button"
                    className={chosen === position ? 'finger current' : 'finger secondary'}
                    aria-pressed={chosen === position}
                    disabled={deleting}
                    onClick={() => choose(position)}
                  >
                    {f.shortFingers[position > 5 ? position - 5 : position]}
                    {enrolled.includes(position) && <span className="badge">{f.enrolledMark}</span>}
                  </button>
                ))}
              </fieldset>
            ))}
          </div>
          {chosen === null && <p className="aside">{f.verification.choose}</p>}
          {chosen !== null && (
            <div className="setting">
              <p>
                {f.chosen}
                <strong>
                  <bdi>{f.fingers[chosen]}</bdi>
                </strong>
              </p>
              {enrolled.includes(chosen) && <p className="aside">{f.replaces}</p>}
              <p className="aside">{f.enrolmentRole}</p>
              {confirming ? (
                <div className="confirm" role="alertdialog" aria-label={f.deleteEnrolment}>
                  <p>{f.deleteAsk(f.fingers[chosen] ?? '')}</p>
                  <div className="actions">
                    <button type="button" className="danger" disabled={deleting} onClick={() => void remove(chosen)}>
                      {deleting ? f.deleting : f.deleteConfirm}
                    </button>
                    <button type="button" className="secondary" disabled={deleting} onClick={() => setConfirming(false)}>
                      {t.cancel}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="actions">
                  {enrolled.includes(chosen) && (
                    <button type="button" onClick={() => setChoosingMethod(true)}>{f.verification.start}</button>
                  )}
                  <button type="button" className={enrolled.includes(chosen) ? 'secondary' : ''} onClick={() => setRunning(true)}>
                    {enrolled.includes(chosen) ? f.enrolAgain : f.enrol}
                  </button>
                  {!enrolled.includes(chosen) && (
                    <button type="button" className="secondary" onClick={() => setVerifying(true)}>{f.verification.start}</button>
                  )}
                  {enrolled.includes(chosen) && (
                    <button type="button" className="secondary" onClick={() => setConfirming(true)}>
                      {f.deleteEnrolment}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
          {message !== null && (
            <p className={message.kind} role={message.kind === 'error' ? 'alert' : 'status'}>
              {message.text}
            </p>
          )}
          <div className="setting identification-entry">
            <h2>{f.identification.entryTitle}</h2>
            <p>{f.identification.entryText}</p>
            <button type="button" disabled={deleting} onClick={() => setIdentifying(true)}>{f.identification.open} <bdi dir="ltr">(1:N)</bdi></button>
          </div>
        </>
      )}
    </section>
  )
}

interface Run {
  phase: 'starting' | 'place' | 'lift' | 'templates' | 'saving' | 'failed'
  placement: number
  placements: number
  minimum: number
  threshold: number
  message: string
  latest: Captured | null
  kept: Array<{ placement: number; image: string; checks: Check[]; keypoints: number }>
  pairs: Pair[]
  error: string
}

const START: Run = { phase: 'starting', placement: 1, placements: 3, minimum: 35, threshold: 57, message: '', latest: null, kept: [], pairs: [], error: '' }

function Enrolment({ finger, onSaved, onLeave }: { finger: number; onSaved: (saved: SavedEnrolment, captures: Record<number, Captured>) => void; onLeave: () => void }) {
  const { t } = useSession()
  const f = t.fingerprint
  const [run, setRun] = useState<Run>(START)
  const [attempt, setAttempt] = useState(0)
  const captures = useRef<Record<number, Captured>>({})
  const done = useRef(false)

  useEffect(() => {
    let active = true
    let started = false
    done.current = false
    captures.current = {}
    setRun(START)
    const stop = window.mbs.onEnrolment((event: EnrolmentEvent) => {
      if (!active || done.current) return
      setRun((current) => next(current, event, t))
      if (event.type === 'kept') captures.current[event.placement] = { image: event.image, checks: event.checks }
      if (event.type === 'saved') {
        done.current = true
        onSaved(event, captures.current)
      }
      if (event.type === 'failed') done.current = true
    })
    // H35: start only after React's synchronous development effect check has finished.
    queueMicrotask(() => {
      if (!active) return
      started = true
      void window.mbs.enrolFingerprint(finger).then((answer) => {
        if (active && !answer.ok && !done.current) {
          done.current = true
          setRun((current) => ({ ...current, phase: 'failed', error: f.errors[answer.error] ?? errorText(answer, t) }))
        }
      })
    })
    return () => {
      active = false
      stop()
      if (started && !done.current) window.mbs.cancelEnrolment() // leaving the screen stops the scanner too
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finger, attempt])

  const prompt =
    run.phase === 'starting' ? f.starting : run.phase === 'lift' ? f.lift : run.phase === 'saving' ? f.saving : run.phase === 'place' ? f.place : ''

  return (
    <section className="enrolment">
      <h1>
        {f.enrolling}
        <bdi>{f.fingers[finger]}</bdi>
      </h1>
      <p className="lead">{f.placementOf(Math.min(run.placement, run.placements), run.placements)}</p>
      <p className="aside">{f.enrolmentRole}</p>
      <ol className="placements" aria-label={f.keptTitle}>
        {Array.from({ length: Math.max(run.placements, run.kept.length) }, (_, i) => (
          <li key={i} className={i < run.kept.length ? 'kept' : i === run.kept.length ? 'now' : ''} />
        ))}
      </ol>
      {run.phase === 'failed' ? (
        <>
          <p className="error" role="alert">
            {run.error}
          </p>
          <div className="actions">
            <button type="button" onClick={() => setAttempt(attempt + 1)}>
              {f.tryAgain}
            </button>
            <button type="button" className="secondary" onClick={onLeave}>
              {f.back}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="notice prompt" role="status" aria-live="polite">
            {run.message && <span>{run.message} </span>}
            {prompt && <strong>{prompt}</strong>}
          </p>
          <button type="button" className="secondary" onClick={() => window.mbs.cancelEnrolment()}>
            {f.cancel}
          </button>
        </>
      )}
      {run.latest !== null && (
        <div className="beside">
          <img className="capture" src={`data:image/png;base64,${run.latest.image}`} alt="" width={280} height={280} />
          <div>
            <h2>{f.checksTitle}</h2>
            <Checks checks={run.latest.checks} />
          </div>
        </div>
      )}
      {run.kept.length > 0 && (
        <>
          <h2>{f.keptTitle}</h2>
          <ul className="thumbs">
            {run.kept.map((kept) => (
              <li key={kept.placement}>
                <img src={`data:image/png;base64,${kept.image}`} alt="" width={96} height={96} />
                <span>{f.placementTab(kept.placement)}</span>
                <span className="aside">{f.keypoints(kept.keypoints)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {run.pairs.length > 0 && (
        <>
          <h2>{f.pairsTitle}</h2>
          <Pairs pairs={run.pairs} threshold={run.threshold} />
        </>
      )}
    </section>
  )
}

function next(run: Run, event: EnrolmentEvent, t: Texts): Run {
  const f = t.fingerprint
  switch (event.type) {
    case 'started':
      return { ...run, placements: event.placements, minimum: event.quality_minimum, threshold: event.threshold }
    case 'place':
      return { ...run, phase: 'place', placement: event.placement }
    case 'rejected':
      return { ...run, latest: { image: event.image, checks: event.checks }, message: f.rejected(event.score, event.minimum) }
    case 'kept': {
      const kept = [...run.kept, { placement: event.placement, image: event.image, checks: event.checks, keypoints: event.keypoints }]
      const enough = kept.length >= run.placements
      return {
        ...run,
        kept,
        latest: { image: event.image, checks: event.checks },
        pairs: [...run.pairs, ...event.pairs],
        message: f.kept(event.placement),
        phase: enough ? 'saving' : run.phase,
      }
    }
    case 'another_placement':
      return { ...run, message: f.another, placements: run.kept.length + 1 }
    case 'lift':
      return { ...run, phase: 'lift' }
    case 'templates':
      return { ...run, phase: 'templates', message: f.preparingTemplates(f.methodNames[event.algorithm] ?? event.algorithm, event.completed, event.total) }
    case 'failed':
      return { ...run, phase: 'failed', error: f.errors[event.error] ?? t.errors[event.error] ?? t.unexpected }
    default:
      return run
  }
}
