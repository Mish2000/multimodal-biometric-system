// H62: the reports' two charts, drawn by hand as SVG (no library, nothing downloaded): the scores over the results'
// rail with the threshold's labelled tick, as the one central object, and the small strip of attempts per day under
// the head's figure. Both run left to right in either language, as charts do (Material's bidirectionality). The marks
// keep Light Table's meanings: mark above the threshold, alert where another registered user led a search, ink not
// above it; no grid and no count axis, a bar's count stands over it. Their sizes come from their boxes.
import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import type { ReportBar, ReportCounts } from '../../../shared/bridge'

export type ScaleName = 'pairs' | 'similarity' | 'points'

// Where a score lies on the rail: pairs on ln(1 + pairs), the axis H60 calibrated the fingerprint on.
export const position = (scale: ScaleName, value: number) => (scale === 'pairs' ? Math.log1p(value) : value)
const TICKS: Record<ScaleName, number[]> = {
  pairs: [0, 10, 100, 1_000, 10_000, 100_000],
  similarity: [0, 0.25, 0.5, 0.75, 1],
  points: [0, 25, 50, 75, 100],
}
export const counted = (counts: ReportCounts) => counts.accepted + counts.rejected

// A bar's parts from its floor up: above the threshold, led by another registered user, not above it.
const PARTS = [
  ['above', (c: ReportCounts) => c.accepted - c.other],
  ['other', (c: ReportCounts) => c.other],
  ['below', (c: ReportCounts) => c.rejected],
] as const

// The size of a box as its layout gives it; nothing is drawn before it is known.
function useBox<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [box, setBox] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const element = ref.current
    if (element === null || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect === undefined) return
      setBox((before) => (before.width === rect.width && before.height === rect.height ? before : { width: rect.width, height: rect.height }))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, box] as const
}

export interface LegendItem {
  key: 'above' | 'other' | 'below'
  label: string
}

// Every score on the results' rail: bars standing over it, each with its count, the threshold's tick labelled at its
// top as the results label it, and the scale's few numbers under the rail. A bar is chosen by pointing at its column
// or by the arrow keys; its range and counts are read out in the line under the rail. For screen readers the chart
// is also a list of its bars.
export function ScoresChart({ bars, scale, threshold, wide, at, locale, caption, hint, legend, readout }: {
  bars: ReportBar[]
  scale: ScaleName
  threshold: number
  wide: boolean // the combined test's rail, as wide as on its result
  at: string // the threshold's label
  locale: string
  caption: string
  hint: string
  legend: LegendItem[]
  readout(bar: ReportBar): ReactNode
}) {
  const [plot, box] = useBox<HTMLDivElement>()
  const [chosen, setChosen] = useState<{ k: number; by: 'pointer' | 'keys' } | null>(null)
  const line = useId()
  const filled = bars.filter((bar) => counted(bar) > 0)
  const selected = chosen === null ? undefined : filled.find((bar) => bar.k === chosen.k)

  const { width: w, height: h } = box
  const rail = wide ? 12 : 6
  const left = 2
  const right = w - 2
  const railTop = h - 24 - rail
  const floor = railTop - 8 // the bars stand here, over the rail
  const top = 32 // room for the threshold's label and the counts
  const p0 = position(scale, bars[0]?.low ?? 0)
  const p1 = position(scale, bars.at(-1)?.high ?? 1)
  const x = (value: number) => left + ((position(scale, value) - p0) / (p1 - p0 || 1)) * (right - left)
  const most = Math.max(1, ...bars.map(counted))
  const tall = (n: number) => (n / most) * Math.max(0, floor - top)

  function pointAt(event: PointerEvent<HTMLDivElement>) {
    const px = event.clientX - event.currentTarget.getBoundingClientRect().left
    const under = bars.find((bar) => px >= x(bar.low) && px < x(bar.high))
    if (under !== undefined && counted(under) > 0) setChosen({ k: under.k, by: 'pointer' })
    else if (chosen?.by === 'pointer') setChosen(null)
  }

  function keys(event: KeyboardEvent<HTMLDivElement>) {
    if (filled.length === 0) return
    const now = selected === undefined ? -1 : filled.indexOf(selected)
    let next: number | null = null
    if (event.key === 'ArrowRight') next = now < 0 ? 0 : Math.min(filled.length - 1, now + 1)
    else if (event.key === 'ArrowLeft') next = now < 0 ? filled.length - 1 : Math.max(0, now - 1)
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = filled.length - 1
    else if (event.key === 'Escape' && chosen !== null) {
      event.preventDefault()
      setChosen(null)
      return
    }
    if (next === null) return
    event.preventDefault()
    setChosen({ k: filled[next]!.k, by: 'keys' })
  }

  const marks: ReactNode[] = []
  const counts: ReactNode[] = []
  let ring: ReactNode = null
  if (w > 0 && h > 0) {
    for (const bar of filled) {
      const x0 = x(bar.low) + 2
      const x1 = x(bar.high) - 2
      let y = floor
      for (const [name, part] of PARTS) {
        const n = part(bar)
        if (n <= 0) continue
        const height = tall(n)
        marks.push(<rect key={`${bar.k}-${name}`} className={name} x={x0} y={y - height} width={Math.max(2, x1 - x0)} height={height} rx={1.5} />)
        y -= height
      }
      const on = selected?.k === bar.k
      counts.push(
        <text key={bar.k} className={on ? 'count count--on' : 'count'} x={(x0 + x1) / 2} y={y - 7} textAnchor="middle">
          {counted(bar).toLocaleString(locale)}
        </text>,
      )
      if (on) ring = <rect className="bar-ring" x={x0 - 4} y={y - 4} width={x1 - x0 + 8} height={floor - y + 8} rx={4} />
    }
  }
  const tx = x(threshold)
  const late = tx > right - 230 // a label near the end reads back from its tick
  const ticks = TICKS[scale].filter((v) => position(scale, v) >= p0 - 1e-9 && position(scale, v) <= p1 + 1e-9)

  return (
    <figure className="distribution">
      <figcaption className="visually-hidden">{caption}</figcaption>
      <div ref={plot} className="distribution__plot" tabIndex={0} role="group" aria-label={caption} aria-describedby={line}
        onKeyDown={keys} onPointerMove={pointAt} onPointerLeave={() => chosen?.by === 'pointer' && setChosen(null)}>
        {w > 0 && h > 0 && (
          <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true">
            <rect className={wide ? 'groove groove--wide' : 'groove'} x={left} y={railTop} width={Math.max(0, right - left)} height={rail} rx={rail / 2} />
            {marks}
            {ring}
            <line className="guide" x1={tx} x2={tx} y1={18} y2={railTop - 6} />
            <rect className="tick" x={tx - 1} y={railTop - 6} width={2} height={rail + 12} />
            <text className="at" x={late ? tx + 1 : tx - 1} y={12} textAnchor={late ? 'end' : 'start'}>{at}</text>
            {counts}
            {ticks.map((value, index) => {
              const vx = x(value)
              const anchor = index === 0 && vx - left < 16 ? 'start' : index === ticks.length - 1 && right - vx < 16 ? 'end' : 'middle'
              return <text key={value} className="end" x={vx} y={h - 5} textAnchor={anchor}>{value.toLocaleString(locale)}</text>
            })}
          </svg>
        )}
      </div>
      <div className="distribution__foot">
        <p className="distribution__readout" id={line} aria-live="polite">{selected === undefined ? hint : readout(selected)}</p>
        <ul className="legend">
          {legend.map((item) => (
            <li key={item.key}><i className={`swatch swatch--${item.key}`} aria-hidden="true" />{item.label}</li>
          ))}
        </ul>
      </div>
      <ul className="visually-hidden">
        {filled.map((bar) => <li key={bar.k}>{readout(bar)}</li>)}
      </ul>
    </figure>
  )
}

// The attempts of each day (each hour today, each week in a long range): bars only, the busiest one's count over it,
// and its two ends named under it, as a rail's ends are. In a low window it keeps the bars alone; the dates are in the
// filters' line. For screen readers its title and one sentence about its busiest day.
export function DaysStrip({ slots, title, ends, locale, describe }: {
  slots: ReportCounts[]
  title: string
  ends: [string, string]
  locale: string
  describe: string | null
}) {
  const [plot, box] = useBox<HTMLDivElement>()
  const { width: w, height: h } = box
  const compact = h < 44
  const floor = compact ? h - 1 : h - 20
  const top = compact ? 2 : 16
  const most = Math.max(1, ...slots.map(counted))
  const step = slots.length > 0 ? w / slots.length : w
  const width = Math.max(2, Math.min(14, step * 0.62))
  const busiest = slots.reduce((best, slot, index) => (counted(slot) > counted(slots[best]!) ? index : best), 0)

  const marks: ReactNode[] = []
  let label: ReactNode = null
  if (w > 0 && h > 0) {
    slots.forEach((slot, index) => {
      const centre = step * (index + 0.5)
      let y = floor
      for (const [name, part] of PARTS) {
        const n = part(slot)
        if (n <= 0) continue
        const height = (n / most) * Math.max(0, floor - top)
        marks.push(<rect key={`${index}-${name}`} className={name} x={centre - width / 2} y={y - height} width={width} height={height} rx={1} />)
        y -= height
      }
      if (!compact && index === busiest && counted(slot) > 0) {
        label = <text className="count" x={centre} y={y - 4} textAnchor="middle">{counted(slot).toLocaleString(locale)}</text>
      }
    })
  }
  const first = Math.max(0, step / 2 - width / 2)
  const last = Math.min(w, step * (slots.length - 0.5) + width / 2)

  return (
    <figure className="perday">
      <figcaption className="perday__title">
        {title}
        {describe !== null && <span className="visually-hidden"> {describe}</span>}
      </figcaption>
      <div ref={plot} className="perday__plot">
        {w > 0 && h > 0 && (
          <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true">
            <line className="base" x1={0} x2={w} y1={floor + 0.5} y2={floor + 0.5} />
            {marks}
            {label}
            {!compact && (
              <>
                <text className="end" x={first} y={h - 4} textAnchor="start">{ends[0]}</text>
                {slots.length > 1 && <text className="end" x={last} y={h - 4} textAnchor="end">{ends[1]}</text>}
              </>
            )}
          </svg>
        )}
      </div>
    </figure>
  )
}
