// H22: the result of a fingerprint 1:1 verification. The verdict, the count and the stage on which the new capture
// and the stored one are joined by the pairs the method counted (H43, H44). The verdict's words enter the moment
// the count decides them; a press plays out whatever is left of the motion at once.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { MatchViewData, VerificationResult } from '../../../shared/bridge'
import { useSession } from '../session'
import { MatchView } from './MatchView'
import { decodeMatchPairs } from './match-data'
import { MatchStage, decodeCapture, type StageColors, type StageState } from './stage'

const WAITING: StageState = { count: 0, verdict: false, done: false }

function colorsNow(): StageColors {
  const style = getComputedStyle(document.documentElement)
  const of = (name: string) => style.getPropertyValue(name)
  return { canvas: of('--bg'), surface: of('--surface'), ink: of('--text'), mist: of('--line'), mark: of('--mark') }
}

export function MatchResult({ result, view, image }: { result: VerificationResult; view: MatchViewData; image: string }) {
  const { t } = useSession()
  const v = t.fingerprint.verification
  const m = t.fingerprint.matches
  const canvas = useRef<HTMLCanvasElement>(null)
  const stage = useRef<MatchStage | null>(null)
  const pairs = useMemo(() => decodeMatchPairs(view.pairs, view.count), [view.pairs, view.count])
  const [shown, setShown] = useState<StageState>(WAITING)
  const [selected, setSelected] = useState(-1)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const element = canvas.current
    if (!element || !pairs) return
    let made: MatchStage | null = null
    let left = false
    const dark = matchMedia('(prefers-color-scheme: dark)')
    const recolor = () => made?.setColors(colorsNow())
    void Promise.all([decodeCapture(image), decodeCapture(view.reference_image)]).then(([fresh, stored]) => {
      if (left) return
      made = new MatchStage(element, { fresh, stored, pairs, threshold: result.threshold }, colorsNow(), {
        reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
        onChange: setShown,
      })
      stage.current = made
      dark.addEventListener('change', recolor)
      made.play()
    }).catch(() => {
      if (!left) setFailed(true)
    })
    return () => {
      left = true
      dark.removeEventListener('change', recolor)
      made?.dispose()
      stage.current = null
    }
  }, [image, view.reference_image, pairs, result.threshold])

  if (!pairs || failed) {
    // Without the stage the same comparison is drawn flat, with the verdict in words at once.
    return (
      <>
        <div className={`verification-result ${result.accepted ? 'matched' : 'unmatched'}`} role="status">
          <h2>{result.accepted ? v.accepted : v.rejected}</h2>
          <p>{v.explanation(result.score, result.threshold)}</p>
        </div>
        <MatchView view={view} image={image} algorithm={result.algorithm} />
      </>
    )
  }

  const count = pairs.length / 4
  const choose = (index: number) => {
    setSelected(index)
    stage.current?.select(index)
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
    choose(selected < 0 ? (step > 0 ? 0 : count - 1) : (selected + step + count) % count)
  }
  const native = (offset: number) => `${Math.round(pairs[selected * 4 + offset]!)}, ${Math.round(pairs[selected * 4 + offset + 1]!)}`
  const scale = Math.max(count, result.threshold, 1) * 1.12

  return (
    <div className="match-result">
      <div className="match-headline" role="status">
        <div>
          <h2 className={shown.verdict ? 'shown' : undefined}>{result.accepted ? v.accepted : v.rejected}</h2>
          <p>{v.explanation(result.score, result.threshold)}</p>
          {result.threshold_provisional && <p className="notice">{t.fingerprint.provisionalExplanation}</p>}
        </div>
        <p className="match-count">
          <strong>{shown.done ? result.score : shown.count}</strong>
          <span>{result.algorithm === 'opencv-sift' ? v.score : v.pores}</span>
        </p>
      </div>
      <div className="match-stage" tabIndex={0} role="group" aria-label={m.stage.label} onKeyDown={onKey}
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
          <div className="match-groove"><i style={{ transform: `scaleX(${(shown.done ? count : shown.count) / scale})` }} /></div>
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
    </div>
  )
}
