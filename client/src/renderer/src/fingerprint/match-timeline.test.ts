import { describe, expect, it } from 'vitest'
import { COUNT_MS, THREADS_START, THREAD_MS, TILT_MS, countAt, easeInOut, easeOut, timeline } from './match-timeline'

// Pairs whose x in the new capture runs against their index, so the order of the threads is not the pairs' own.
function pairsOf(count: number): Float32Array {
  const pairs = new Float32Array(count * 4)
  for (let index = 0; index < count; index += 1) pairs.set([900 - index * 5, 500, 10, 20], index * 4)
  return pairs
}

describe('the curves of the result moment (H22)', () => {
  it('are the two CSS curves', () => {
    expect(easeOut(0)).toBe(0)
    expect(easeOut(1)).toBeCloseTo(1, 6)
    expect(easeOut(0.5)).toBeCloseTo(0.966, 3)
    expect(easeInOut(0.25)).toBeCloseTo(0.053, 3)
    expect(easeInOut(0.5)).toBeCloseTo(0.596, 3)
    for (let x = 0.05; x <= 1; x += 0.05) expect(easeOut(x)).toBeGreaterThan(easeOut(x - 0.05))
  })

  it('count a thread when it is drawn to 98% of its length', () => {
    expect(COUNT_MS).toBe(215)
    expect(easeOut(COUNT_MS / THREAD_MS)).toBeGreaterThanOrEqual(0.98)
  })
})

describe('the timeline of the threads (H22)', () => {
  it('starts the threads from the left of the new capture, when the tilt is nearly done', () => {
    const moment = timeline(pairsOf(142), 57)
    expect(moment.starts[141]).toBe(THREADS_START) // the smallest x
    expect(moment.starts[0]).toBeCloseTo(850, 3)
    expect(moment.total).toBe(1230)
    expect(easeInOut(THREADS_START / TILT_MS)).toBeGreaterThan(0.9)
  })

  it('shows a match the moment the count passes the threshold, before the threads end', () => {
    const moment = timeline(pairsOf(142), 57)
    expect(Math.round(moment.verdictAt)).toBe(731)
    expect(countAt(moment, moment.verdictAt - 1)).toBe(57)
    expect(countAt(moment, moment.verdictAt)).toBe(58)
    expect(countAt(moment, moment.total)).toBe(142)
  })

  it('shows a non-match when its last thread is counted', () => {
    const moment = timeline(pairsOf(9), 57)
    expect(Math.round(moment.total)).toBe(893)
    expect(countAt(moment, moment.verdictAt - 1)).toBe(8)
    expect(countAt(moment, moment.verdictAt)).toBe(9)
    expect(moment.verdictAt).toBeLessThan(moment.total)
  })

  it('has a verdict without any pair', () => {
    const moment = timeline(new Float32Array(0), 57)
    expect(moment).toMatchObject({ verdictAt: THREADS_START, total: TILT_MS })
    expect(countAt(moment, 5000)).toBe(0)
  })

  it('counts every thread once the moment is over, whatever the rounding', () => {
    const moment = timeline(pairsOf(601), 57)
    expect(countAt(moment, moment.total)).toBe(601)
  })
})
