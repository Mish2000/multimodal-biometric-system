// H18, H43, H44: the pairs counted by the highest-scoring comparison, in the two native image frames:
// OpenCV SIFT's RANSAC inliers, or the pore pairs of Pore SIFT and the learned descriptor.
import { useMemo, useState, type PointerEvent } from 'react'
import type { MatchViewData } from '../../../shared/bridge'
import { useSession } from '../session'
import { decodeMatchPairs, nearestMatch } from './match-data'

const IMAGE_SIZE = 1000
const REFERENCE_X = 1100
const VIEW_WIDTH = REFERENCE_X + IMAGE_SIZE

export function MatchView({ view, image, algorithm }: { view: MatchViewData; image: string; algorithm: string }) {
  const { t } = useSession()
  const m = t.fingerprint.matches
  const kind = algorithm === 'opencv-sift' ? m.points : m.pores
  const pairs = useMemo(() => decodeMatchPairs(view.pairs, view.count), [view.pairs, view.count])
  const [selected, setSelected] = useState(0)
  const [showAll, setShowAll] = useState(true)
  const path = useMemo(() => {
    if (!pairs) return ''
    const lines: string[] = []
    for (let index = 0; index < pairs.length; index += 4) {
      lines.push(`M${pairs[index]} ${pairs[index + 1]}L${pairs[index + 2]! + REFERENCE_X} ${pairs[index + 3]}`)
    }
    return lines.join(' ')
  }, [pairs])
  const pick = (event: PointerEvent<SVGSVGElement>) => {
    if (!pairs || view.count === 0) return
    const matrix = event.currentTarget.getScreenCTM()
    if (!matrix) return
    const { x, y } = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
    if (!Number.isFinite(x) || !Number.isFinite(y)) return
    if (x < 0 || x > VIEW_WIDTH || y < 0 || y >= IMAGE_SIZE || (x > IMAGE_SIZE && x < REFERENCE_X)) return
    const reference = x >= REFERENCE_X
    setSelected(nearestMatch(pairs, reference ? x - REFERENCE_X : x, y, reference))
  }
  const chosen = pairs && view.count > 0 ? Math.min(Math.max(selected, 0), view.count - 1) : null
  const offset = chosen === null ? 0 : chosen * 4
  const highlight = chosen !== null && pairs
    ? `M${pairs[offset]} ${pairs[offset + 1]}L${pairs[offset + 2]! + REFERENCE_X} ${pairs[offset + 3]}`
    : ''

  return (
    <section className="match-view" aria-label={kind.title}>
      <h2>{kind.title}</h2>
      {pairs === null ? <p className="notice">{m.unavailable}</p> : (
        <>
          <p>{kind.explanation(view.placement, view.count)}</p>
          <p className="match-rule">{kind.rule}</p>
          <figure>
            <div className="match-labels" dir="ltr">
              <span dir="auto">{m.probe}</span>
              <span dir="auto">{m.reference(view.placement)}</span>
            </div>
            <svg className="match-drawing" viewBox={`0 0 ${VIEW_WIDTH} ${IMAGE_SIZE}`} width={VIEW_WIDTH} height={IMAGE_SIZE}
              role="img" aria-label={kind.drawing(view.count)} onPointerMove={pick} onPointerDown={pick}>
              <image href={`data:image/png;base64,${image}`} x={0} y={0} width={IMAGE_SIZE} height={IMAGE_SIZE} />
              <image href={`data:image/png;base64,${view.reference_image}`} x={REFERENCE_X} y={0} width={IMAGE_SIZE} height={IMAGE_SIZE} />
              {showAll && <path className="match-connections" d={path} vectorEffect="non-scaling-stroke" />}
              {chosen !== null && (
                <g className="match-selected">
                  <path className="match-halo" d={highlight} vectorEffect="non-scaling-stroke" />
                  <path d={highlight} vectorEffect="non-scaling-stroke" />
                  <circle cx={pairs[offset]} cy={pairs[offset + 1]} r={12} vectorEffect="non-scaling-stroke" />
                  <circle cx={pairs[offset + 2]! + REFERENCE_X} cy={pairs[offset + 3]} r={12} vectorEffect="non-scaling-stroke" />
                </g>
              )}
            </svg>
            <figcaption>{view.count === 0 ? kind.empty : m.hint}</figcaption>
          </figure>
          {chosen !== null && (
            <div className="match-controls">
              <label className="match-toggle">
                <input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />
                {kind.showAll}
              </label>
              <label className="match-picker">
                <span>{m.selected(chosen + 1, view.count)}</span>
                <input type="range" min={1} max={view.count} value={chosen + 1} aria-label={m.choose}
                  onChange={(event) => setSelected(Number(event.target.value) - 1)} />
              </label>
            </div>
          )}
        </>
      )}
    </section>
  )
}
