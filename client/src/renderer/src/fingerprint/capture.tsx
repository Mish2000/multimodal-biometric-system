// H59: the capture of a screen's last fingerprint result. For ten minutes from when it was taken, another method may
// compare it again without scanning; the server opens it from the attempt's sealed probe, so only the attempt's id
// travels back, never the image.
import { useEffect, useState } from 'react'
import type { CaptureOrigin, Check, FingerprintAlgorithm } from '../../../shared/bridge'
import { useSession } from '../session'
import { Plate } from '../ui/Plate'

export const CAPTURE_REUSE_MS = 10 * 60 * 1000

export interface LastCapture {
  /** The attempt of the last result, which the server follows to the capture. */
  attemptId: string
  /** When the capture was taken. */
  takenAt: string
  image: string
  /** The checks it passed when it was taken; a comparison again repeats none. */
  checks: Check[]
  algorithm: FingerprintAlgorithm
  accepted: boolean
  score: number
  /** Every method this capture has been compared with on this screen. */
  compared: FingerprintAlgorithm[]
  /** Whether its ten minutes had not yet ended when the result was left for the methods. */
  open: boolean
}

/** The capture of a result, adding its method to those already compared when the capture is the same one. Called
 * when the result is left for the methods, so the capture's age is read then. */
export function captureOf(result: { attempt_id: string; algorithm: string; accepted: boolean; score: number; capture: CaptureOrigin },
  latest: { image: string; checks: Check[] }, earlier: LastCapture | null): LastCapture {
  const algorithm = result.algorithm as FingerprintAlgorithm
  const same = earlier !== null && result.capture.reused && earlier.takenAt === result.capture.at
  return {
    attemptId: result.attempt_id, takenAt: result.capture.at, image: latest.image,
    checks: same ? earlier.checks : latest.checks, algorithm, accepted: result.accepted, score: result.score,
    compared: same ? [...earlier.compared.filter((code) => code !== algorithm), algorithm] : [algorithm],
    open: Date.now() - Date.parse(result.capture.at) < CAPTURE_REUSE_MS,
  }
}

/** Whether the capture may still be compared again; the answer turns false by itself when its ten minutes end. */
export function useFreshCapture(capture: LastCapture | null): boolean {
  const [expired, setExpired] = useState<string | null>(null)
  useEffect(() => {
    if (capture === null) return
    // When the ten minutes end, the choice to compare again disappears on its own.
    const left = Math.max(0, Date.parse(capture.takenAt) + CAPTURE_REUSE_MS - Date.now())
    const timer = window.setTimeout(() => setExpired(capture.takenAt), left)
    return () => window.clearTimeout(timer)
  }, [capture])
  return capture !== null && capture.open && expired !== capture.takenAt
}

export function captureTime(at: string, language: string): string {
  return new Date(at).toLocaleTimeString(language === 'he' ? 'he-IL' : 'en-GB', { hour: '2-digit', minute: '2-digit' })
}

/** The capture on its plate, with when it was taken and what the last method made of it (key screen 4b). */
export function CaptureCard({ capture, mode }: { capture: LastCapture; mode: 'verify' | 'identify' }) {
  const { t, language } = useSession()
  const f = t.fingerprint
  const c = f.capture
  const time = captureTime(capture.takenAt, language)
  const verdict = mode === 'verify'
    ? (capture.accepted ? c.verdicts.match : c.verdicts.noMatch)
    : (capture.accepted ? c.verdicts.found : c.verdicts.notFound)
  return (
    <figure className="capture-card">
      <Plate image={capture.image} size={104} />
      <figcaption>
        <strong>{c.title(time)}</strong>
        <span>{c.before(f.methodNames[capture.algorithm] ?? capture.algorithm, verdict, capture.score)}</span>
        <span className="capture-card-window">{c.window}</span>
      </figcaption>
    </figure>
  )
}
