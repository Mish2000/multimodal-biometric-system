// H41: one fresh capture, a bounded gallery search and an anonymous ranked result.
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import type { FingerprintAlgorithm, FingerprintMethod, IdentificationEvent, IdentificationResult } from '../../../shared/bridge'
import { useSession } from '../session'
import { errorText } from '../texts'
import { Checks, type Captured } from './Journey'
import { MatchView } from './MatchView'
import { MethodChoices } from './MethodChoices'

type Phase = 'ready' | 'starting' | 'preparing' | 'place' | 'checking' | 'lift' | 'extracting' | 'searching' | 'saving' | 'identified' | 'failed' | 'cancelled'
interface Run {
  phase: Phase
  latest: Captured | null
  rejection: string
  completed: number
  total: number
  enrolments: number
  prepared: number
  preparationTotal: number
  error: string
  result: IdentificationResult | null
}
const START: Run = { phase: 'starting', latest: null, rejection: '', completed: 0, total: 0, enrolments: 0,
  prepared: 0, preparationTotal: 0, error: '', result: null }

export function Identification({ enrolled, methods, methodError, onReloadMethods, onLeave }: {
  enrolled: boolean
  methods: FingerprintMethod[]
  methodError: string
  onReloadMethods: () => void
  onLeave: () => void
}) {
  const { t, call, language } = useSession()
  const f = t.fingerprint
  const i = f.identification
  const [run, setRun] = useState<Run>({ ...START, phase: 'ready' })
  const [attempt, setAttempt] = useState(0)
  const [algorithm, setAlgorithm] = useState<FingerprintAlgorithm>('opencv-sift')
  const [stopping, setStopping] = useState(false)
  const control = useRef<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    heading.current?.focus()
  }, [run.phase === 'identified', run.phase === 'failed', run.phase === 'cancelled'])

  useEffect(() => {
    if (!enrolled || attempt === 0) return
    const runId = crypto.randomUUID()
    control.current = runId
    let active = true
    let finished = false
    let started = false
    setRun(START)
    setStopping(false)
    const fail = (code: string) => {
      finished = true
      setStopping(false)
      setRun((current) => ({ ...current, phase: code === 'cancelled' ? 'cancelled' : 'failed', error: code }))
    }
    const stop = window.mbs.onIdentification(runId, (event: IdentificationEvent) => {
      if (!active || finished) return
      switch (event.type) {
        case 'started':
          setRun((current) => ({ ...current, total: event.gallery_size, enrolments: event.enrolments }))
          break
        case 'preparing_templates':
          setRun((current) => ({ ...current, phase: 'preparing', prepared: event.completed, preparationTotal: event.total }))
          break
        case 'place':
        case 'checking':
        case 'lift':
        case 'extracting':
        case 'saving':
          setRun((current) => ({ ...current, phase: event.type }))
          break
        case 'rejected':
          setRun((current) => ({ ...current, latest: event, rejection: f.rejected(event.score, event.minimum) }))
          break
        case 'captured':
          setRun((current) => ({ ...current, latest: event, rejection: '' }))
          break
        case 'searching':
          setRun((current) => ({ ...current, phase: 'searching', completed: event.completed, total: event.total }))
          break
        case 'identified':
          finished = true
          setStopping(false)
          setRun((current) => ({ ...current, phase: 'identified', result: event }))
          break
        case 'failed':
          fail(event.error)
          break
      }
    })
    // H35, H41: development effect replay must not start a second scan.
    queueMicrotask(() => {
      if (!active) return
      started = true
      void window.mbs.identifyFingerprint(runId, algorithm).then((answer) => {
        if (!active || finished || answer.ok) return
        fail(answer.error)
        if (answer.status === 401) void call('me')
      })
    })
    return () => {
      active = false
      stop()
      if (started && !finished) window.mbs.cancelIdentification(runId)
      control.current = null
    }
    // Language and theme changes do not restart capture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enrolled, attempt, algorithm])

  const result = run.result
  const ended = result !== null || run.phase === 'failed' || run.phase === 'cancelled'
  const methodName = f.methodNames[algorithm] ?? algorithm
  const selectedMethod = methods.find((method) => method.code === algorithm)
  const scoreLabel = algorithm === 'opencv-sift' ? f.verification.score : f.verification.pores
  const prompts: Record<Phase, string> = {
    ready: '', starting: i.preparing, place: i.place, checking: f.verification.checking,
    preparing: f.preparingTemplates(methodName, run.prepared, run.preparationTotal),
    lift: f.lift, extracting: i.extracting, searching: i.searching(run.completed, run.total),
    saving: f.verification.saving, identified: '', failed: '', cancelled: i.cancelled,
  }
  const stage: Record<Phase, number> = {
    ready: -1, starting: 0, preparing: -1, place: 0, lift: 0, checking: 1, extracting: 2, searching: 2,
    saving: 3, identified: 3, failed: -1, cancelled: -1,
  }
  const error = i.errors[run.error] ?? f.verification.errors[run.error] ?? f.errors[run.error]
    ?? errorText({ ok: false, status: 0, error: run.error }, t)
  const needsEnrolment = !enrolled || run.error === 'not_enrolled'
  const leader = result?.candidates[0]
  const maximum = result ? Math.max(Math.ceil(result.score / 100) * 100, result.threshold * 2, 1) : 1

  return (
    <section className="identification verification">
      <h1 ref={heading} tabIndex={-1}>{i.title} <bdi dir="ltr">(1:N)</bdi></h1>
      <p className="lead">{i.lead}</p>
      {run.phase !== 'ready' && <p><strong>{methodName}</strong></p>}
      {needsEnrolment ? (
        <>
          <p className="notice">{i.enrolFirst}</p>
          <div className="actions">
            <button type="button" onClick={onLeave}>{i.enrol}</button>
            <Link to="/">{f.verification.home}</Link>
          </div>
        </>
      ) : run.phase === 'ready' ? (
        <>
          <p>{i.explanation(methodName)}</p>
          <p className="aside">{i.privacy}</p>
          <MethodChoices methods={methods} algorithm={algorithm} onChoose={setAlgorithm} error={methodError}
            onRetry={onReloadMethods} purpose="identification" />
          <div className="actions">
            <button type="button" disabled={!selectedMethod?.available} onClick={() => setAttempt((value) => value + 1)}>{i.begin}</button>
            <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
          </div>
        </>
      ) : (
        <>
          <ol className="verification-steps" aria-label={i.title}>
            {i.stages.map((name, index) => (
              <li key={name} aria-current={!ended && stage[run.phase] === index ? 'step' : undefined}
                className={result !== null || index < stage[run.phase] ? 'complete' : ''}>{name}</li>
            ))}
          </ol>
          {result ? (
            <div className={`verification-result ${result.accepted ? 'matched' : 'unmatched'}`} role="status">
              <h2>{result.accepted ? i.found : i.notFound}</h2>
              <p>{i.decision(result.score, result.threshold)}</p>
              {result.threshold_provisional && <p className="notice">{f.provisionalExplanation}</p>}
              {result.accepted && leader && <p><strong>{result.tied_leaders > 1 ? i.tie(result.tied_leaders)
                : leader.own ? i.yourFinger(f.fingers[leader.finger ?? 0] ?? '') : i.otherUser}</strong></p>}
              <div className="verification-score">
                <meter min={0} max={maximum} value={result.score} low={result.threshold}
                  high={result.threshold + 1} optimum={maximum} aria-label={scoreLabel} />
                <span className="threshold-marker" style={{ insetInlineStart: `${result.threshold / maximum * 100}%` }} aria-hidden="true" />
              </div>
              <div className="score-axis" aria-hidden="true"><span>0</span><span>{maximum}</span></div>
              <div className="score-labels"><strong>{scoreLabel} {result.score}</strong><span>{f.verification.threshold(result.threshold)}</span></div>
              <p>{f.verification.saved}</p>
            </div>
          ) : run.phase === 'failed' ? (
            <p className="error" role="alert">{error}</p>
          ) : (
            <div className="notice prompt" role="status" aria-live="polite">
              {run.rejection && <p>{run.rejection}</p>}
              <strong>{stopping ? i.stopping : prompts[run.phase]}</strong>
            </div>
          )}
          {run.phase === 'preparing' && (
            <div className="gallery-progress">
              <progress max={run.preparationTotal} value={run.prepared} aria-label={i.preparationProgress} />
            </div>
          )}
          {!ended && run.phase !== 'preparing' && run.total > 0 && (
            <div className="gallery-progress">
              <p>{i.gallery(run.enrolments, run.total)}</p>
              <progress max={run.total} value={run.completed} aria-label={i.progress} />
              <div className="gallery-sweep" aria-hidden="true">
                {Array.from({ length: 12 }, (_, index) => (
                  <span key={index} className={index < run.completed / run.total * 12 ? 'complete' : ''} />
                ))}
              </div>
            </div>
          )}
          <div className="actions">
            {ended ? (
              <>
                <button type="button" onClick={() => setAttempt((value) => value + 1)}>{result ? i.again : f.tryAgain}</button>
                {result && <button type="button" className="secondary" onClick={() => {
                  setAttempt(0)
                  setRun({ ...START, phase: 'ready' })
                  onReloadMethods()
                }}>{f.verification.changeMethod}</button>}
                <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
              </>
            ) : (
              <button type="button" className="secondary" disabled={stopping || run.phase === 'saving'} onClick={() => {
                if (control.current) {
                  setStopping(true)
                  window.mbs.cancelIdentification(control.current)
                }
              }}>{f.cancel}</button>
            )}
          </div>
          {result && (
            <>
              <p>{i.gallery(result.enrolments, result.gallery_size)}</p>
              <p className="aside">{i.privacy}</p>
              <div className="table-wrap">
                <table>
                  <caption>{i.ranking(result.candidates.length, result.enrolments)}</caption>
                  <thead><tr><th>{i.rank}</th><th>{i.candidate}</th><th>{scoreLabel}</th><th>{f.verification.decision}</th></tr></thead>
                  <tbody>{result.candidates.map((candidate) => (
                    <tr key={candidate.rank}>
                      <td>{candidate.rank}</td>
                      <td>{candidate.own ? i.yourFinger(f.fingers[candidate.finger ?? 0] ?? '') : i.otherUser}</td>
                      <td><strong>{candidate.score}</strong></td>
                      <td>{candidate.accepted ? f.verification.match : f.verification.noMatch}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="aside">{f.verification.duration} {f.verification.seconds(result.duration_ms)}</p>
              {/* H45: the caller's own highest-ranked print only (H18). */}
              {result.match_view && run.latest ? (
                <>
                  <p>{i.drawingOf(f.fingers[result.match_view.finger] ?? '', result.match_view.rank)}</p>
                  <MatchView key={result.attempt_id} view={result.match_view} image={run.latest.image} algorithm={result.algorithm} />
                </>
              ) : !result.candidates.some((candidate) => candidate.own) && <p className="aside">{i.noDrawing}</p>}
            </>
          )}
          {run.latest && (
            <details className="verification-details" open={result === null}>
              <summary>{f.verification.details}</summary>
              <div className="beside">
                <img className="capture" src={`data:image/png;base64,${run.latest.image}`} alt={f.verification.image} width={280} height={280} />
                <div><h2>{f.checksTitle}</h2><Checks checks={run.latest.checks} /></div>
              </div>
              {result && <dl>
                <dt>{f.verification.at}</dt><dd>{new Date(result.at).toLocaleString(language === 'he' ? 'he-IL' : 'en-GB')}</dd>
                <dt>{f.verification.origin}</dt><dd><bdi>{result.threshold_origin}</bdi></dd>
              </dl>}
            </details>
          )}
        </>
      )}
    </section>
  )
}
