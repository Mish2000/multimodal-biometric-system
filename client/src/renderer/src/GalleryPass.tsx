// H50, H56: the pass over the enrolled gallery of a face or voice identification. The search itself is one database
// query of a few milliseconds, so the pass of the specification plays once, for about 0.6 s, when the answer arrives;
// the time shown stays the server's processing time, and with Windows' animation effects off the pass is skipped.
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'

export const PASS_MS = 600
const CELLS = 12

function reducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// Whether the pass still plays, and the result's heading, which takes the focus when it ends.
export function usePass(): [boolean, RefObject<HTMLHeadingElement | null>] {
  const [passing, setPassing] = useState(() => !reducedMotion())
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (!passing) {
      heading.current?.focus()
      return
    }
    const timer = window.setTimeout(() => setPassing(false), PASS_MS)
    return () => window.clearTimeout(timer)
  }, [passing])
  return [passing, heading]
}

export function GalleryPass({ comparing, children }: { comparing: string; children: ReactNode }) {
  return (
    <div className="gallery-progress" role="status">
      <p>{comparing}</p>
      <div className="gallery-sweep passing" aria-hidden="true">
        {Array.from({ length: CELLS }, (_, index) => <span key={index} style={{ animationDelay: `${index * 35}ms` }} />)}
      </div>
      {children}
    </div>
  )
}
