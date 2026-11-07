// "How your fingerprint is stored" (H33): after an enrolment, the template it made, step by step, from the
// data the server sent once from memory before sealing it. The data lives only in this screen's state.
import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import type { Check, SavedEnrolment } from '../../../shared/bridge'
import { useSession } from '../session'
import {
  decodePoints, descriptorOf, heatmapLines, megabytes, nearest, sealedBytes, SIFT_BINS, SIFT_CELLS, type Points,
} from './data'

export interface Captured {
  image: string // PNG, base64
  checks: Check[]
}

const VIEW = 440 // the capture's size on screen, in CSS pixels (the capture is 1000 x 1000)
const STEPS = 6

function cssColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// A canvas drawn by `draw`, again whenever `deps` change; nothing is drawn where canvases are unavailable.
function useCanvas(draw: (context: CanvasRenderingContext2D, canvas: HTMLCanvasElement) => void, deps: unknown[]) {
  const ref = useRef<HTMLCanvasElement | null>(null)
  useEffect(() => {
    const canvas = ref.current
    const context = canvas?.getContext?.('2d') ?? null
    if (canvas && context) draw(context, canvas)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return ref
}

export function Checks({ checks }: { checks: Check[] }) {
  const { t } = useSession()
  return (
    <ul className="checks">
      {checks.map((check) => (
        <li key={check.name} className={check.passed ? 'met' : 'missing'}>
          <span className="mark" aria-hidden="true">
            {check.passed ? '✓' : '✗'}
          </span>
          <strong>{t.fingerprint.checks[check.name] ?? check.name}</strong> <span className="aside">{check.detail}</span>
        </li>
      ))}
    </ul>
  )
}

function Print({ image, points, chosen, onPick }: { image: string; points?: Points; chosen?: number; onPick?: (index: number) => void }) {
  const overlay = useCanvas(
    (context, canvas) => {
      const scale = canvas.width / 1000
      context.clearRect(0, 0, canvas.width, canvas.height)
      if (!points) return
      context.fillStyle = cssColor('--accent', '#1f5fbf')
      context.globalAlpha = chosen === undefined ? 0.75 : 0.35
      for (let i = 0; i < points.count; i++) context.fillRect((points.xy[2 * i] ?? 0) * scale - 1, (points.xy[2 * i + 1] ?? 0) * scale - 1, 2, 2)
      if (chosen !== undefined && chosen >= 0) {
        context.globalAlpha = 1
        context.strokeStyle = cssColor('--error', '#b42318')
        context.lineWidth = 2
        context.beginPath()
        context.arc((points.xy[2 * chosen] ?? 0) * scale, (points.xy[2 * chosen + 1] ?? 0) * scale, 9, 0, 2 * Math.PI)
        context.stroke()
      }
    },
    [points, chosen],
  )
  const pick = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!points || !onPick) return
    const box = event.currentTarget.getBoundingClientRect()
    const scale = 1000 / box.width
    onPick(nearest(points, (event.clientX - box.left) * scale, (event.clientY - box.top) * scale))
  }
  return (
    <div className="print" style={{ width: VIEW, height: VIEW }}>
      <img src={`data:image/png;base64,${image}`} alt="" width={VIEW} height={VIEW} />
      <canvas ref={overlay} width={VIEW} height={VIEW} onPointerMove={onPick ? pick : undefined} />
    </div>
  )
}

// SIFT's own layout of the 128 numbers: 4 x 4 cells, each with an arrow per orientation bin.
function Compasses({ values }: { values: Uint8Array }) {
  const ref = useCanvas(
    (context, canvas) => {
      const cell = canvas.width / SIFT_CELLS
      context.clearRect(0, 0, canvas.width, canvas.height)
      context.strokeStyle = cssColor('--line', '#d9dde3')
      for (let i = 0; i <= SIFT_CELLS; i++) {
        context.beginPath()
        context.moveTo(i * cell, 0)
        context.lineTo(i * cell, canvas.height)
        context.moveTo(0, i * cell)
        context.lineTo(canvas.width, i * cell)
        context.stroke()
      }
      context.strokeStyle = cssColor('--accent', '#1f5fbf')
      context.lineWidth = 2
      for (let row = 0; row < SIFT_CELLS; row++)
        for (let column = 0; column < SIFT_CELLS; column++) {
          const cx = (column + 0.5) * cell
          const cy = (row + 0.5) * cell
          for (let bin = 0; bin < SIFT_BINS; bin++) {
            const value = values[(row * SIFT_CELLS + column) * SIFT_BINS + bin] ?? 0
            const length = (value / 255) * cell * 0.48
            const angle = (bin * 2 * Math.PI) / SIFT_BINS
            context.beginPath()
            context.moveTo(cx, cy)
            context.lineTo(cx + Math.cos(angle) * length, cy - Math.sin(angle) * length)
            context.stroke()
          }
        }
    },
    [values],
  )
  return <canvas ref={ref} className="compasses" width={256} height={256} />
}

function Strip({ values }: { values: Uint8Array }) {
  return (
    <div className="strip" aria-hidden="true">
      {Array.from(values, (value, i) => (
        <span key={i} style={{ opacity: 0.08 + (0.92 * value) / 255 }} />
      ))}
    </div>
  )
}

function Heatmap({ points }: { points: Points }) {
  const { t } = useSession()
  const { rows, values, height } = useMemo(() => heatmapLines(points, 360), [points])
  const ref = useCanvas(
    (context, canvas) => {
      const image = context.createImageData(canvas.width, canvas.height)
      for (let line = 0; line < height; line++)
        for (let column = 0; column < 128; column++) {
          const shade = Math.round(Math.min(255, (values[line * 128 + column] ?? 0) * 1.2))
          const at = (line * 128 + column) * 4
          image.data.set([shade, shade, Math.min(255, shade + 40), 255], at)
        }
      context.putImageData(image, 0, 0)
    },
    [values, height],
  )
  return (
    <>
      <canvas ref={ref} className="heatmap" width={128} height={height} />
      <p className="aside">{t.fingerprint.rowsPerLine(rows)}</p>
    </>
  )
}

export function Journey({ saved, captures, finger, onDone }: { saved: SavedEnrolment; captures: Record<number, Captured>; finger: number; onDone: () => void }) {
  const { t } = useSession()
  const f = t.fingerprint
  const [step, setStep] = useState(0)
  const [tab, setTab] = useState(0)
  const [chosen, setChosen] = useState<number | undefined>(undefined)
  const [numbers, setNumbers] = useState(false)
  const template = saved.templates[tab]
  const points = useMemo(() => (template ? decodePoints(template.points, template.descriptors) : null), [template])
  const capture = template ? captures[template.placement] : undefined

  useEffect(() => setChosen(undefined), [tab])
  if (!template || !capture || !points) return null
  const vector = chosen !== undefined && chosen >= 0 ? descriptorOf(points, chosen) : null

  const tabs = (
    <div className="tabs" role="tablist">
      {saved.templates.map((each, i) => (
        <button key={each.id} type="button" role="tab" aria-selected={i === tab} className={i === tab ? 'current' : 'secondary'} onClick={() => setTab(i)}>
          {f.placementTab(each.placement)}
        </button>
      ))}
    </div>
  )

  return (
    <section className="journey">
      <h1>{f.journeyTitle}</h1>
      <p className="lead">
        {t.modalities.fingerprint}: <bdi>{f.fingers[finger]}</bdi>
      </p>
      <p className="notice">{f.journeyLead}</p>
      <p>{f.templatesPrepared(['opencv-sift', ...(saved.prepared_methods ?? []).map((method) => method.algorithm)]
        .map((code) => f.methodNames[code] ?? code).join(', '))}</p>
      <ol className="steps">
        {f.steps.map((name, i) => (
          <li key={name} className={i === step ? 'current' : i < step ? 'done' : ''}>
            <button type="button" className="link" onClick={() => setStep(i)} aria-current={i === step ? 'step' : undefined}>
              {name}
            </button>
          </li>
        ))}
      </ol>
      <p className="aside">{f.stepOf(step + 1, STEPS)}</p>
      <div className="step" key={step}>
        <h2>{f.steps[step]}</h2>
        {step >= 1 && step <= 4 && <p className="notice">{f.demonstratedMethod(f.methodNames[template.algorithm] ?? template.algorithm)}</p>}
        {step === 0 && (
          <>
            <p>{f.capturesText}</p>
            {tabs}
            <div className="beside">
              <Print image={capture.image} />
              <Checks checks={capture.checks} />
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <p>{f.pointsText(points.count)}</p>
            {tabs}
            <Print image={capture.image} points={points} />
          </>
        )}
        {step === 2 && (
          <>
            <p>{f.vectorText}</p>
            {tabs}
            <div className="beside">
              <Print image={capture.image} points={points} chosen={chosen ?? -1} onPick={setChosen} />
              <div className="vector">
                {vector === null || chosen === undefined ? (
                  <p className="aside">{f.vectorHint}</p>
                ) : (
                  <>
                    <p>
                      <strong>{f.point(chosen + 1, points.xy[2 * chosen] ?? 0, points.xy[2 * chosen + 1] ?? 0)}</strong>
                    </p>
                    <Compasses values={vector} />
                    <Strip values={vector} />
                    <button type="button" className="secondary" onClick={() => setNumbers(!numbers)}>
                      {numbers ? f.hideNumbers : f.showNumbers}
                    </button>
                    {numbers && (
                      <table className="numbers" dir="ltr">
                        <tbody>
                          {Array.from({ length: SIFT_CELLS * SIFT_CELLS }, (_, cell) => (
                            <tr key={cell}>
                              {Array.from(vector.subarray(cell * SIFT_BINS, (cell + 1) * SIFT_BINS), (value, bin) => (
                                <td key={bin}>{value}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </>
                )}
              </div>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <p>{f.templateText(points.count, megabytes(template.template_length))}</p>
            {tabs}
            <Heatmap points={points} />
          </>
        )}
        {step === 4 && (
          <>
            <p>{f.databaseText}</p>
            {tabs}
            <h3>{f.row}</h3>
            <table className="row" dir="ltr">
              <tbody>
                <tr><th>id</th><td><code>{template.id}</code></td></tr>
                <tr><th>sample_id</th><td><code>{template.sample_id}</code></td></tr>
                <tr><th>algorithm</th><td><code>{template.algorithm}</code></td></tr>
                <tr><th>version</th><td><code>{template.version}</code></td></tr>
                <tr><th>created_at</th><td><code>{template.created_at}</code></td></tr>
                <tr><th>data</th><td>{f.bytes(template.sealed.length)}</td></tr>
              </tbody>
            </table>
            <div className="sealed" dir="ltr">
              {sealedBytes(template.sealed).map((part) => (
                <span key={part.part} className={`part ${part.part}`}>
                  <span className="hex">
                    {part.hex.join(' ')}
                    {part.hex.length < part.total ? ' …' : ''}
                  </span>
                  <span className="label">
                    {f.parts[part.part]}: {f.bytes(part.total)}
                  </span>
                </span>
              ))}
            </div>
            <h3>{f.structureTitle}</h3>
            <div className="structure">
              <div className="box">{f.enrolmentBox}</div>
              <div className="samples">
                {saved.samples.map((sample) => (
                  <div key={sample.id} className="sample">
                    <div className="box">{f.sampleBox(sample.placement)}</div>
                    <div className="box filled">{f.methodNames['opencv-sift']}</div>
                    {saved.prepared_methods?.map((method) => (
                      <div key={method.algorithm} className="box filled">{f.methodNames[method.algorithm] ?? method.algorithm}</div>
                    ))}
                    {saved.pending_methods.map((method) => (
                      <div key={method} className="box pending" title={f.pendingMethod}>
                        {f.methodNames[method] ?? method}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              {saved.pending_methods.length > 0 && <p className="aside">{f.pendingMethod}</p>}
            </div>
          </>
        )}
        {step === 5 && (
          <>
            <p>{f.acceptedText(saved.threshold)}</p>
            <h3>{f.refereeTitle}</h3>
            <Pairs pairs={saved.pairs} threshold={saved.threshold} />
            {(saved.method_comparisons?.length ?? 0) > 1 && (
              <div className="method-comparisons">
                <h3>{f.comparisonTitle}</h3>
                <p className="aside">{f.comparisonExplanation}</p>
                {saved.method_comparisons?.filter((method) => method.algorithm !== 'opencv-sift').map((method) => (
                  <section key={method.algorithm} aria-label={f.methodNames[method.algorithm]} className="method-comparison">
                    <h4>{f.methodNames[method.algorithm]}</h4>
                    <p>{f.verification.threshold(method.threshold)}{method.threshold_provisional ? ` · ${f.provisional}` : ''}</p>
                    <Pairs pairs={method.pairs} threshold={method.threshold} />
                  </section>
                ))}
              </div>
            )}
            {saved.not_kept.length > 0 && <p className="aside">{f.notKept(saved.not_kept.join(', '))}</p>}
          </>
        )}
      </div>
      <div className="actions">
        <button type="button" className="secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>
          {f.previous}
        </button>
        {step < STEPS - 1 ? (
          <button type="button" onClick={() => setStep(step + 1)}>
            {f.next}
          </button>
        ) : (
          <button type="button" onClick={onDone}>
            {f.done}
          </button>
        )}
      </div>
    </section>
  )
}

export function Pairs({ pairs, threshold }: { pairs: SavedEnrolment['pairs']; threshold: number }) {
  const { t } = useSession()
  const f = t.fingerprint
  const top = Math.max(threshold * 2, ...pairs.map((p) => p.score ?? 0))
  return (
    <ul className="pairs">
      {pairs.map((pair) => (
        <li key={`${pair.probe}-${pair.reference}`} className={pair.accepted ? 'met' : 'missing'}>
          <span className="name">{f.pair(pair.probe, pair.reference)}</span>
          <span className="bar" aria-hidden="true">
            <span className="fill" style={{ width: `${(100 * (pair.score ?? 0)) / top}%` }} />
            <span className="mark" style={{ insetInlineStart: `${(100 * threshold) / top}%` }} />
          </span>
          <strong>{pair.score ?? 0}</strong>
          <span className="aside">{pair.accepted ? f.above(threshold) : f.notAbove(threshold)}</span>
        </li>
      ))}
    </ul>
  )
}
