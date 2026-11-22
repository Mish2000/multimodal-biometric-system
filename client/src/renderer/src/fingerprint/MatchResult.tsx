// H22: the result of a fingerprint 1:1 verification. The verdict, the count and the stage on which the new capture
// and the stored one are joined by the pairs the method counted (H43, H44). The verdict's words enter the moment
// the count decides them, with the lines that explain them; a press or Escape anywhere plays out whatever is left
// of the motion at once.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { MatchViewData, VerificationResult } from '../../../shared/bridge'
import { useSession } from '../session'
import { Notice } from '../ui/Notice'
import { ScoreMeter } from '../ui/ScoreMeter'
import { MatchView } from './MatchView'
import { decodeMatchPairs } from './match-data'
import { MatchStage, decodeCapture, type StageColors, type StageState } from './stage'

const WAITING: StageState = { verdict: false, done: false }

/** The stage's colours of the current theme. A non-match is a result said in ink, its threads and points too (H22). */
function colorsNow(accepted: boolean): StageColors {
  const style = getComputedStyle(document.documentElement)
  const of = (name: string) => style.getPropertyValue(name)
  return { canvas: of('--canvas'), surface: of('--surface'), ink: of('--ink'), mist: of('--mist'), mark: of(accepted ? '--mark' : '--ink') }
}

/** The rail's length in pairs: a little beyond the larger of the count and the threshold. */
const railOf = (count: number, threshold: number) => Math.max(count, threshold, 1) * 1.12

export function MatchResult({ result, view, image, tilted = false }: {
  result: VerificationResult
  view: MatchViewData
  image: string
  /** A result after an earlier one on the same screen: its moment starts from the reliefs. */
  tilted?: boolean
}) {
  const { t } = useSession()
  const v = t.fingerprint.verification
  const m = t.fingerprint.matches
  const canvas = useRef<HTMLCanvasElement>(null)
  const counter = useRef<HTMLElement>(null)
  const fill = useRef<HTMLElement>(null)
  const stage = useRef<MatchStage | null>(null)
  const skipped = useRef(false)
  const pairs = useMemo(() => decodeMatchPairs(view.pairs, view.count), [view.pairs, view.count])
  const [shown, setShown] = useState<StageState>(WAITING)
  const [ready, setReady] = useState(false)
  const [selected, setSelected] = useState(-1)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const element = canvas.current
    if (!element || !pairs) return
    let made: MatchStage | null = null
    let left = false
    const dark = matchMedia('(prefers-color-scheme: dark)')
    const recolor = () => made?.setColors(colorsNow(result.accepted))
    const rail = railOf(pairs.length / 4, result.threshold)
    void Promise.all([decodeCapture(image), decodeCapture(view.reference_image)]).then(([fresh, stored]) => {
      if (left) return
      made = new MatchStage(element, { fresh, stored, pairs, threshold: result.threshold }, colorsNow(result.accepted), {
        reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
        tilted,
        onChange: setShown,
        // Written here and not through React, so that the number lands in the frame that draws its thread.
        onCount: (count) => {
          if (counter.current) counter.current.textContent = String(count)
          if (fill.current) fill.current.style.transform = `scaleX(${count / rail})`
        },
      })
      stage.current = made
      dark.addEventListener('change', recolor)
      setReady(true)
      made.play()
      if (skipped.current) made.finish()
    }).catch(() => {
      if (!left) setFailed(true)
    })
    return () => {
      left = true
      dark.removeEventListener('change', recolor)
      made?.dispose()
      stage.current = null
    }
  }, [image, view.reference_image, pairs, result.threshold, result.accepted, tilted])

  // While the moment plays, a press or Escape anywhere on the page plays out the rest, even before the stage exists.
  useEffect(() => {
    if (shown.done) return
    const skip = (event: Event) => {
      if (event.type === 'keydown' && (event as globalThis.KeyboardEvent).key !== 'Escape') return
      if (!stage.current?.finish()) skipped.current = true
    }
    window.addEventListener('keydown', skip)
    window.addEventListener('pointerdown', skip)
    return () => {
      window.removeEventListener('keydown', skip)
      window.removeEventListener('pointerdown', skip)
    }
  }, [shown.done])

  if (!pairs || failed) {
    // Without the stage the same comparison is drawn flat, with the verdict in words at once.
    return (
      <>
        <div className="verification-result" role="status">
          <ScoreMeter score={result.score} threshold={result.threshold} scale="count"
            label={result.algorithm === 'opencv-sift' ? v.score : v.pores} thresholdLabel={v.threshold(result.threshold)}
            accepted={result.accepted} verdict={<h2>{result.accepted ? v.accepted : v.rejected}</h2>}
            explanation={v.explanation(result.score, result.threshold)} />
        </div>
        <MatchView view={view} image={image} algorithm={result.algorithm} />
        <p>{v.saved}</p>
        {!result.accepted && <p>{v.retryHint}</p>}
      </>
    )
  }

  const count = pairs.length / 4
  const choose = (index: number, instant = false) => {
    setSelected(index)
    stage.current?.select(index, instant)
  }
  const fine = () => matchMedia('(hover: hover) and (pointer: fine)').matches
  const at = (event: PointerEvent<HTMLElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    return stage.current?.pick(event.clientX - box.left, event.clientY - box.top) ?? -1
  }
  const onKey = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') return void stage.current?.finish()
    const step = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>)[event.key]
    if (!step || count === 0) return
    event.preventDefault()
    if (stage.current?.finish() || !shown.done) return
    choose(selected < 0 ? (step > 0 ? 0 : count - 1) : (selected + step + count) % count, true)
  }
  const native = (offset: number) => `${Math.round(pairs[selected * 4 + offset]!)}, ${Math.round(pairs[selected * 4 + offset + 1]!)}`
  const scale = railOf(count, result.threshold)
  const verdict = result.accepted ? v.accepted : v.rejected
  const explanation = v.explanation(result.score, result.threshold)
  // What explains the verdict enters with it: the explanation just after the heading, the notes just after that.
  const later = (part = '') => `match-later${part ? ` ${part}` : ''}${shown.verdict ? ' shown' : ''}`

  return (
    <div className={result.accepted ? 'match-result' : 'match-result below'}>
      <div className="match-headline">
        <div>
          <h2 className={shown.verdict ? 'shown' : undefined}>{verdict}</h2>
          <p className={later()}>{explanation}</p>
          {result.threshold_provisional && <Notice className={later('match-note')}>{t.fingerprint.provisionalExplanation}</Notice>}
        </div>
        <p className="match-count" aria-hidden="true">
          <strong ref={counter}>0</strong>
          <span>{result.algorithm === 'opencv-sift' ? v.score : v.pores}</span>
        </p>
      </div>
      {/* Read out once, when the verdict is shown: the count that climbs to it is not spoken. */}
      <p className="visually-hidden" role="status">{shown.verdict ? `${verdict}. ${explanation}` : ''}</p>
      <div className={ready ? 'match-stage ready' : 'match-stage'} tabIndex={0} role="group" aria-label={m.stage.label} onKeyDown={onKey}
        onPointerDown={(event) => { if (!stage.current?.finish() && shown.done && !fine()) choose(at(event)) }}
        onPointerMove={(event) => { if (shown.done && fine()) { const index = at(event); if (index !== selected) choose(index) } }}
        onPointerLeave={() => { if (fine() && selected !== -1) choose(-1) }}>
        <canvas ref={canvas} aria-hidden="true" />
        <div className="match-plates" dir="ltr" aria-hidden="true">
          <span dir="auto">{m.probe}</span>
          <span dir="auto">{m.reference(view.placement)}</span>
        </div>
      </div>
      <div className="match-rail" aria-hidden="true">
        <div className="match-track">
          <div className="match-groove"><i ref={fill} /></div>
          <b style={{ insetInlineStart: `${(result.threshold / scale) * 100}%` }} />
        </div>
        <div className="match-ends">
          <span>0</span>
          <span style={{ insetInlineStart: `max(${(result.threshold / scale) * 100}%, 6rem)` }}>{v.threshold(result.threshold)}</span>
        </div>
      </div>
      <p className="match-pair">
        {!shown.done ? '' : selected >= 0 ? m.stage.pair(selected + 1, count, native(0), native(2)) : count > 0 ? m.stage.hint : ''}
      </p>
      <p>{v.saved}</p>
      {!result.accepted && <p className={later('match-note')}>{v.retryHint}</p>}
    </div>
  )
}
