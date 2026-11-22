// The one-capture verification flow (H15, H35). Progress follows real server events; a result appears
// only after persistence. A fresh run id prevents a cancelled operation from updating the next one.
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import type { VerificationEvent, VerificationResult, FingerprintAlgorithm } from '../../../shared/bridge'
import { useSession } from '../session'
import { errorText } from '../texts'
import { Notice, type Tone } from '../ui/Notice'
import { Plate } from '../ui/Plate'
import { ScoreMeter } from '../ui/ScoreMeter'
import { Steps } from '../ui/Steps'
import { Tag } from '../ui/Tag'
import { Checks, type Captured } from './Journey'
import { MatchResult } from './MatchResult'
import { stageSupported } from './stage'
import { MatchView } from './MatchView'

type Phase = 'starting' | 'preparing' | 'place' | 'checking' | 'lift' | 'comparing' | 'saving' | 'verified' | 'failed' | 'cancelled'
interface Run {
  phase: Phase
  latest: Captured | null
  rejection: string
  completed: number
  total: number
  error: string
  result: VerificationResult | null
}
const START: Run = { phase: 'starting', latest: null, rejection: '', completed: 0, total: 3, error: '', result: null }

export function Verification({ finger, enrolled, algorithm, onLeave, onEnrol, onChangeMethod }: {
  finger: number
  enrolled: boolean
  algorithm: FingerprintAlgorithm
  onLeave: () => void
  onEnrol: () => void
  onChangeMethod: () => void
}) {
  const { t, language, call } = useSession()
  const f = t.fingerprint
  const v = f.verification
  const [run, setRun] = useState<Run>(START)
  const [attempt, setAttempt] = useState(0)
  // H22: once a result has been shown on this screen, the next one starts from the reliefs and skips the tilt.
  const [earlier, setEarlier] = useState(false)
  const [stopping, setStopping] = useState(false)
  const control = useRef<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  const verified = run.phase === 'verified'
  const failed = run.phase === 'failed'
  const cancelled = run.phase === 'cancelled'
  useEffect(() => {
    heading.current?.focus()
  }, [verified, failed, cancelled])

  useEffect(() => {
    if (!enrolled) return
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
    const stop = window.mbs.onVerification(runId, (event: VerificationEvent) => {
      if (!active || finished) return
      switch (event.type) {
        case 'started':
          setRun((current) => ({ ...current, total: event.references }))
          break
        case 'preparing_templates':
          setRun((current) => ({ ...current, phase: 'preparing', completed: event.completed, total: event.total }))
          break
        case 'place':
        case 'checking':
        case 'lift':
        case 'saving':
          setRun((current) => ({ ...current, phase: event.type }))
          break
        case 'rejected':
          setRun((current) => ({ ...current, latest: event, rejection: f.rejected(event.score, event.minimum) }))
          break
        case 'captured':
          setRun((current) => ({ ...current, latest: event, rejection: '' }))
          break
        case 'comparing':
          setRun((current) => ({ ...current, phase: 'comparing', completed: event.completed, total: event.total }))
          break
        case 'verified':
          finished = true
          setStopping(false)
          setRun((current) => ({ ...current, phase: 'verified', result: event }))
          break
        case 'failed':
          fail(event.error)
          break
      }
    })
    // React's development check mounts, cleans up and mounts the effect again. Wait until that
    // synchronous check finishes before starting the physical operation (H35).
    queueMicrotask(() => {
      if (!active) return
      started = true
      void window.mbs.verifyFingerprint(finger, runId, algorithm).then((answer) => {
        if (!active || finished || answer.ok) return
        fail(answer.error)
        if (answer.status === 401) void call('me') // keep the normal expired-session navigation
      })
    })
    return () => {
      active = false
      stop()
      if (started && !finished) window.mbs.cancelVerification(runId)
      control.current = null
    }
    // A language or theme update must not start another capture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finger, enrolled, algorithm, attempt])

  const prompts = {
    starting: v.preparing, place: v.place, checking: v.checking, lift: f.lift,
    preparing: f.preparingTemplates(f.methodNames[algorithm] ?? algorithm, run.completed, run.total),
    comparing: v.comparing(run.completed, run.total), saving: v.saving,
    verified: '', failed: '', cancelled: v.cancelled,
  }
  const stages: Record<Phase, number> = {
    starting: 0, preparing: -1, place: 0, lift: 0, checking: 1, comparing: 2, saving: 3, verified: 3, failed: -1, cancelled: -1,
  }
  // The scanner's red dot while it waits for the finger or for its lift; a turning ring while the system works.
  const tone: Tone = run.phase === 'cancelled' ? 'info' : !stopping && (run.phase === 'place' || run.phase === 'lift') ? 'live' : 'busy'
  const result = run.result
  const scoreLabel = algorithm === 'opencv-sift' ? v.score : v.pores
  // H22: the result on its stage, where the page can draw one; otherwise the same comparison is drawn flat.
  const staged = stageSupported()
  const ended = result !== null || run.phase === 'failed' || run.phase === 'cancelled'
  const error = run.error === 'server_unreachable'
    ? v.networkError
    : v.errors[run.error] ?? f.errors[run.error] ?? errorText({ ok: false, status: 0, error: run.error }, t)
  const needsEnrolment = ['not_enrolled', 'templates_unavailable', 'template_version_mismatch'].includes(run.error)

  return (
    <section className="verification">
      <h1 ref={heading} tabIndex={-1}>{v.title}</h1>
      <p className="lead"><bdi>{f.fingers[finger]}</bdi></p>
      <p><strong>{f.methodNames[algorithm]}</strong></p>
      {!enrolled ? (
        <>
          <Notice still>{v.enrolFirst}</Notice>
          <div className="actions">
            <button type="button" className="primary" onClick={onEnrol}>{f.enrol}</button>
            <Link to="/">{v.home}</Link>
            <button type="button" className="quiet" onClick={onLeave}>{f.back}</button>
          </div>
        </>
      ) : (
        <>
          <p className="aside">{f.methodComparison[algorithm]}</p>
          <Steps label={v.title} steps={v.stages} current={ended ? -1 : stages[run.phase]}
            reached={(index) => result !== null || index < stages[run.phase]} />
          {result !== null && staged && result.match_view && run.latest ? (
            <MatchResult key={result.attempt_id} result={result} view={result.match_view} image={run.latest.image} tilted={earlier} />
          ) : result !== null ? (
            <div className="verification-result" role="status">
              <ScoreMeter score={result.score} threshold={result.threshold} scale="count" label={scoreLabel}
                thresholdLabel={v.threshold(result.threshold)} accepted={result.accepted}
                verdict={<h2>{result.accepted ? v.accepted : v.rejected}</h2>}
                explanation={v.explanation(result.score, result.threshold)} />
              {result.threshold_provisional && <Notice still>{f.provisionalExplanation}</Notice>}
              <p>{v.saved}</p>
              {!result.accepted && <p>{v.retryHint}</p>}
            </div>
          ) : run.phase === 'failed' ? (
            <Notice tone="alert" role="alert">{error}</Notice>
          ) : (
            <div className="prompt" role="status" aria-live="polite">
              <Notice tone={tone}>
                {run.rejection && <p>{run.rejection}</p>}
                <strong>{stopping ? v.stopping : prompts[run.phase]}</strong>
              </Notice>
            </div>
          )}
          <div className="actions">
            {ended ? (
              <>
                {needsEnrolment ? (
                  <button type="button" className="primary" onClick={onEnrol}>{f.enrolAgain}</button>
                ) : (
                  <button type="button" className="primary" onClick={() => {
                    if (result) setEarlier(true)
                    setAttempt((value) => value + 1)
                  }}>{result ? v.again : f.tryAgain}</button>
                )}
                {result?.accepted && <button type="button" className="secondary" onClick={onChangeMethod}>{v.changeMethod}</button>}
                <button type="button" className="quiet" onClick={onLeave}>{f.back}</button>
              </>
            ) : (
              <button type="button" className="secondary" disabled={stopping || run.phase === 'saving'} onClick={() => {
                if (control.current !== null) {
                  setStopping(true)
                  window.mbs.cancelVerification(control.current)
                }
              }}>{f.cancel}</button>
            )}
          </div>
          {result !== null && (
            <>
              {!staged && result.match_view && run.latest && (
                <MatchView key={result.attempt_id} view={result.match_view} image={run.latest.image} algorithm={result.algorithm} />
              )}
              <div className="table-wrap">
                <table>
                  <caption>{v.comparisons}</caption>
                  <thead>
                    <tr><th>{v.placement}</th><th>{scoreLabel}</th><th>{v.decision}</th></tr>
                  </thead>
                  <tbody>
                    {result.comparisons.map((comparison) => (
                      <tr key={comparison.placement} className={comparison.score === result.score ? 'decides' : undefined}>
                        <td>{f.placementTab(comparison.placement)}</td>
                        <td>
                          <span className="score-cell">
                            <span className="number">{comparison.score}</span>
                            {comparison.score === result.score && <Tag tone="ink">{v.highest}</Tag>}
                          </span>
                        </td>
                        <td>{!comparison.computed ? v.noFeatures : comparison.accepted ? v.match : v.noMatch}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="aside">{v.duration} {v.seconds(result.duration_ms)}</p>
            </>
          )}
          {run.latest !== null && (
            <details className="verification-details" open={result === null}>
              <summary>{v.details}</summary>
              <div className="beside">
                <Plate image={run.latest.image} size={280} label={v.image} state={run.rejection ? 'rejected' : 'captured'} />
                <div><h2>{f.checksTitle}</h2><Checks checks={run.latest.checks} /></div>
              </div>
              {result && <dl>
                <dt>{v.at}</dt><dd>{new Date(result.at).toLocaleString(language === 'he' ? 'he-IL' : 'en-GB')}</dd>
                <dt>{v.origin}</dt><dd><bdi>{result.threshold_origin}</bdi></dd>
              </dl>}
            </details>
          )}
        </>
      )}
    </section>
  )
}
