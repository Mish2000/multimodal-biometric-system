// Light Table's sample plate (H22): the surface a fingerprint capture lies on. The print is drawn in ink from the
// capture's own grey levels, exactly as the stage shows it from above (relief.ts), so the dark theme shows its
// negative; the raw grey image is never pasted. A plate exists only with a capture on it. What a method found is drawn
// over it by the caller, as children.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { decodedCapture, paintPlate, plateColors } from '../fingerprint/relief'

export function Plate({ image, size, label, state = 'captured', className, children }: {
  /** The capture's PNG, in Base64, as the server sent it. */
  image: string
  /** The plate's side, in CSS pixels. */
  size: number
  /** The capture's name for assistive technology; without one the plate is decoration. */
  label?: string | undefined
  state?: 'captured' | 'rejected'
  className?: string | undefined
  children?: ReactNode
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [drawn, setDrawn] = useState(false)

  useEffect(() => {
    const element = canvas.current
    // A canvas the processor draws: the plate is written pixel by pixel once, and such a canvas keeps its picture when
    // the graphics card's surfaces are made again (a resized window). Without a 2D canvas (the tests' page) nothing
    // is drawn.
    if (!element || !element.getContext?.('2d', { willReadFrequently: true })) return
    let current = true
    const paint = () => {
      void decodedCapture(image).then(({ image: decoded, relief }) => {
        if (!current) return
        const side = Math.round(size * Math.min(window.devicePixelRatio || 1, 2))
        element.width = element.height = side
        paintPlate(element, decoded, relief, plateColors())
        setDrawn(true)
      }, () => undefined)
    }
    paint()
    // The theme's change repaints the print in the other theme's ink.
    const dark = window.matchMedia?.('(prefers-color-scheme: dark)')
    dark?.addEventListener('change', paint)
    return () => {
      current = false
      dark?.removeEventListener('change', paint)
    }
  }, [image, size])

  return (
    <div className={className ? `plate ${className}` : 'plate'} data-state={state} data-drawn={drawn ? 'yes' : undefined}
      style={{ width: size, height: size }}>
      {/* What is drawn over the print comes first, so it is what a pointer meets. */}
      {children}
      <canvas ref={canvas} className="plate-print" role={label ? 'img' : undefined} aria-label={label}
        aria-hidden={label ? undefined : true} />
    </div>
  )
}
