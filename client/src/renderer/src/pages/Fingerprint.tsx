// The fingerprint screen (H15, H33): choose a finger, enrol it from the scanner with live guidance, then see
// how its template is stored. Verification and identification follow in the next build steps.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Check, EnrolmentEvent, Pair, SavedEnrolment } from '../../../shared/bridge'
import { Checks, Journey, Pairs, type Captured } from '../fingerprint/Journey'
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
    })
  }, [call])
  useEffect(load, [load])

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
        <p className="aside">{t.loading}</p>
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
                    onClick={() => choose(position)}
                  >
                    {f.shortFingers[position > 5 ? position - 5 : position]}
                    {enrolled.includes(position) && <span className="badge">{f.enrolledMark}</span>}
                  </button>
                ))}
              </fieldset>
            ))}
          </div>
          {chosen !== null && (
            <div className="setting">
              <p>
                {f.chosen}
                <strong>
                  <bdi>{f.fingers[chosen]}</bdi>
                </strong>
              </p>
              {enrolled.includes(chosen) && <p className="aside">{f.replaces}</p>}
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
                  <button type="button" onClick={() => setRunning(true)}>
                    {enrolled.includes(chosen) ? f.enrolAgain : f.enrol}
                  </button>
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
          <p className="aside">{f.laterSteps}</p>
        </>
      )}
    </section>
  )
}

interface Run {
  phase: 'starting' | 'place' | 'lift' | 'saving' | 'failed'
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
    done.current = false
    captures.current = {}
    setRun(START)
    const stop = window.mbs.onEnrolment((event: EnrolmentEvent) => {
      if (done.current) return
      setRun((current) => next(current, event, t))
      if (event.type === 'kept') captures.current[event.placement] = { image: event.image, checks: event.checks }
      if (event.type === 'saved') {
        done.current = true
        onSaved(event, captures.current)
      }
      if (event.type === 'failed') done.current = true
    })
    void window.mbs.enrolFingerprint(finger).then((answer) => {
      if (!answer.ok && !done.current) {
        done.current = true
        setRun((current) => ({ ...current, phase: 'failed', error: f.errors[answer.error] ?? errorText(answer, t) }))
      }
    })
    return () => {
      stop()
      if (!done.current) window.mbs.cancelEnrolment() // leaving the screen stops the scanner too
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
            <strong>{prompt}</strong>
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
    case 'failed':
      return { ...run, phase: 'failed', error: f.errors[event.error] ?? t.errors[event.error] ?? t.unexpected }
    default:
      return run
  }
}
