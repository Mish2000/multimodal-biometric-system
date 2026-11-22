// Light Table's score meter (H22): a score against its threshold. The rail runs from 0 to a display maximum, the mark
// fills it up to the score and an ink tick stands at the threshold. A match and a non-match differ in words and in
// where the fill ends against the tick, never in green and red. The drawn rail is decoration; screen readers get the
// native meter, whose value is the score itself.
import type { CSSProperties, ReactNode } from 'react'

/** Similarities (face, voice) run from 0 to 1. Counts have no upper bound, so their rail runs to the larger of four
 * times the threshold and a little beyond the score: the threshold sits at a quarter of the rail or before it. */
export function railMaximum(score: number, threshold: number, scale: 'count' | 'similarity'): number {
  return scale === 'similarity' ? 1 : Math.max(threshold * 4, score * 1.15, 1)
}

const share = (value: number, maximum: number) => Math.min(1, Math.max(0, value / maximum))

export function ScoreMeter({ score, threshold, scale, label, shown, thresholdLabel, accepted, verdict, explanation, compact = false, children }: {
  score: number
  threshold: number
  scale: 'count' | 'similarity'
  /** What the number is, such as "Matching points" or "Similarity"; also the meter's name. */
  label: string
  /** The score as written, when it is not the plain number (a similarity to three places). */
  shown?: string
  thresholdLabel: string
  /** A score at or below the threshold is said in ink, the number and the fill alike. */
  accepted: boolean
  /** The verdict's heading, at the start of the head; the figure then stands at its end. */
  verdict?: ReactNode
  explanation?: ReactNode
  compact?: boolean
  children?: ReactNode
}) {
  const maximum = railMaximum(score, threshold, scale)
  const style = { '--fill': share(score, maximum), '--at': share(threshold, maximum) } as CSSProperties
  const figure = (
    <p className="score-figure">
      <span className="score-value" dir="ltr">{shown ?? String(score)}</span>
      <span className="score-label">{label}</span>
    </p>
  )
  return (
    <div className={`score${compact ? ' compact' : ''}${accepted ? '' : ' below'}`} style={style}>
      {verdict !== undefined ? <div className="score-head">{verdict}{figure}</div> : figure}
      <div className="score-rail" aria-hidden="true">
        <span className="score-groove"><i /></span>
        <b />
      </div>
      <div className="score-ends" aria-hidden="true">
        <span>0</span>
        <span className="score-at">{thresholdLabel}</span>
        {scale === 'similarity' && <span className="score-max">1</span>}
      </div>
      <meter className="visually-hidden" min={0} max={maximum} value={Math.max(0, score)} aria-label={label} />
      {explanation !== undefined && <p className="score-explain">{explanation}</p>}
      {children}
    </div>
  )
}
