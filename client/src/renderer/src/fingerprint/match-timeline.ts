// H22: the times of the 1:1 result's showcase moment, in milliseconds. One thing leads at a time: the two captures
// tilt and rise, and the threads between the matched pairs start when that is nearly done. Each thread is counted
// when it lands, and the verdict is shown the moment the count decides it, not when the motion ends.

export const TILT_MS = 600
export const THREADS_START = 400
/** The time over which the threads of a full comparison start; fewer pairs take less. */
export const SPREAD_MS = 450
/** One thread's own time. */
export const THREAD_MS = 380
/** A press plays out whatever is left of the moment within this time. */
export const SKIP_MS = 150
/** The stage's fade when the moment plays again, and all that moves with reduced motion. */
export const FADE_MS = 160
const FULL = 142 // the pairs of a comfortable match, for which SPREAD_MS was tuned

/** A cubic-bezier curve exactly as CSS computes it. */
export function bezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const at = (a: number, b: number, t: number) => 3 * (1 - t) * (1 - t) * t * a + 3 * (1 - t) * t * t * b + t * t * t
  return (x) => {
    if (!(x > 0)) return 0
    if (x >= 1) return 1
    const wanted = x
    let low = 0
    let high = 1
    for (let step = 0; step < 26; step += 1) {
      const middle = (low + high) / 2
      if (at(x1, x2, middle) < wanted) low = middle
      else high = middle
    }
    return at(y1, y2, (low + high) / 2)
  }
}

/** What arrives: each thread. */
export const easeOut = bezier(0.23, 1, 0.32, 1)
/** What moves while it stays on screen: the captures. */
export const easeInOut = bezier(0.77, 0, 0.175, 1)

/** A thread counts once it is drawn to 98% of its length. */
export const COUNT_MS = (() => {
  for (let x = 0; x <= 1; x += 0.005) if (easeOut(x) >= 0.98) return Math.round(x * THREAD_MS)
  return THREAD_MS
})()

export interface Timeline {
  /** When each pair's thread starts, by the pair's own index. */
  starts: Float32Array
  /** When the count decides the verdict. */
  verdictAt: number
  total: number
}

/**
 * The threads sweep across the new capture from left to right: most start early and the last ones further
 * apart, so the sweep slows into its end. `pairs` holds probe x, y and reference x, y for each pair (H43).
 */
export function timeline(pairs: Float32Array, threshold: number): Timeline {
  const count = pairs.length / 4
  const order = Array.from({ length: count }, (_, index) => index).sort((a, b) => pairs[a * 4]! - pairs[b * 4]! || a - b)
  const spread = SPREAD_MS * Math.min(1, Math.sqrt(count / FULL))
  const starts = new Float32Array(count)
  order.forEach((pair, rank) => {
    starts[pair] = THREADS_START + spread * (count > 1 ? rank / (count - 1) : 0) ** 1.5
  })
  if (count === 0) return { starts, verdictAt: THREADS_START, total: TILT_MS }
  // A match needs more pairs than the threshold, so the pair after it decides; without one, the last pair does.
  const deciding = order[Math.min(Math.max(0, Math.floor(threshold)), count - 1)]!
  return { starts, verdictAt: starts[deciding]! + COUNT_MS, total: Math.max(TILT_MS, THREADS_START + spread + THREAD_MS) }
}

/** The threads that have landed by `time`. */
export function countAt(moment: Timeline, time: number): number {
  if (time >= moment.total) return moment.starts.length
  let count = 0
  for (const start of moment.starts) if (time >= start + COUNT_MS) count += 1
  return count
}
