// Light Table's line icons (H22): drawn at 24 units with a 1.8 stroke, round caps and joins, in the current colour.
// Each one stands beside words that say the same, so it is hidden from assistive technology.
import type { ReactElement } from 'react'

export type IconName = 'check' | 'ring' | 'info' | 'alert' | 'eye' | 'eye-off'

const EYE = 'M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12z'

const SHAPES: Record<IconName, ReactElement> = {
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  ring: <circle cx="12" cy="12" r="7" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5" /><path d="M12 7.5h.01" /></>,
  alert: <><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5" /><path d="M12 16.5h.01" /></>,
  eye: <><path d={EYE} /><circle cx="12" cy="12" r="3" /></>,
  'eye-off': <><path d={EYE} /><circle cx="12" cy="12" r="3" /><path d="M4 4l16 16" /></>,
}

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {SHAPES[name]}
    </svg>
  )
}
