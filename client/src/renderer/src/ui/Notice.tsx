// Light Table's notice (H22): a message inside a flow. `live` says that a device is capturing now and carries the
// sensor's red dot, the only red besides a waiting plate's rim; `busy` is a step in progress; `done` is something
// completed; `alert` is a problem and how to go on; `info` is context. The icon and, for an alert, the boundary carry
// the tone: no tinted grounds and no coloured stripes. The role is the caller's, since a notice that stands in a
// live region must not announce itself twice.
//
// A notice that arrives (an answer, a problem, a step under way) enters with a short rise; one that is part of its
// screen's own content, shown with the screen, is `still` and appears with it. A notice that appears busy waits
// BUSY_AFTER_MS before it shows: the face's and the voice's checks answer in about 60 to 130 ms, and a notice that
// came and went in that time would only flash, with the actions below it jumping. One that turns busy is already
// on the screen and stays.
import { useEffect, useState, type ReactNode } from 'react'
import { Icon } from './Icon'

export type Tone = 'info' | 'done' | 'alert' | 'live' | 'busy'

export const BUSY_AFTER_MS = 200

function Mark({ tone }: { tone: Tone }) {
  if (tone === 'live') return <span className="live-dot" />
  if (tone === 'busy') return <span className="busy-ring" />
  return <Icon name={tone === 'done' ? 'check' : tone === 'alert' ? 'alert' : 'info'} />
}

export function Notice({ tone = 'info', role, label, className, still = false, actions, children }: {
  tone?: Tone
  role?: 'alert' | 'status' | 'alertdialog' | undefined
  label?: string | undefined
  className?: string | undefined
  /** Part of its screen's content, shown with the screen: no entrance of its own. */
  still?: boolean
  actions?: ReactNode
  children: ReactNode
}) {
  const [waiting, setWaiting] = useState(() => tone === 'busy')
  useEffect(() => {
    if (!waiting) return
    const timer = window.setTimeout(() => setWaiting(false), BUSY_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [waiting])
  if (waiting && tone === 'busy') return null

  const classes = ['notice', still ? 'still' : '', className ?? ''].filter(Boolean).join(' ')
  return (
    <div className={classes} data-tone={tone} role={role} aria-label={label}>
      <span className="notice-mark" aria-hidden="true">
        <Mark tone={tone} />
      </span>
      <div className="notice-body">
        {children}
        {actions !== undefined && <div className="actions">{actions}</div>}
      </div>
    </div>
  )
}
