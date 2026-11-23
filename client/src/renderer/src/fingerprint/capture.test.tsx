// @vitest-environment jsdom
// H59: the capture another method may compare again: which methods compared it, and for how long it is offered.
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CAPTURE_REUSE_MS, captureOf, useFreshCapture } from './capture'

const LATEST = { image: 'cG5n', checks: [] }
const result = (at: string, reused: boolean, algorithm = 'opencv-sift') => ({
  attempt_id: '00000000-0000-4000-8000-000000000002', algorithm, accepted: true, score: 90,
  capture: { attempt_id: '00000000-0000-4000-8000-000000000001', at, reused },
})

afterEach(() => {
  vi.useRealTimers()
})

describe('the capture another method may compare again (H59)', () => {
  it('collects the methods that compared one capture, and starts over with a new capture', () => {
    const at = new Date().toISOString()
    const first = captureOf(result(at, false), LATEST, null)
    expect(first).toMatchObject({ compared: ['opencv-sift'], open: true, takenAt: at })
    const second = captureOf(result(at, true, 'pore-sift'), LATEST, first)
    expect(second.compared).toEqual(['opencv-sift', 'pore-sift'])
    expect(captureOf(result(at, true, 'opencv-sift'), LATEST, second).compared).toEqual(['pore-sift', 'opencv-sift'])
    const later = new Date(Date.now() + 1000).toISOString()
    expect(captureOf(result(later, false, 'pore-sift'), LATEST, second).compared).toEqual(['pore-sift'])
  })

  it('stops offering a capture when ten minutes have passed since it was taken', () => {
    vi.useFakeTimers({ now: new Date('2026-11-23T10:00:00Z') })
    const capture = captureOf(result('2026-11-23T09:55:00Z', false), LATEST, null)
    const { result: fresh } = renderHook(() => useFreshCapture(capture))
    expect(fresh.current).toBe(true)
    act(() => { vi.advanceTimersByTime(CAPTURE_REUSE_MS / 2 - 1) })
    expect(fresh.current).toBe(true)
    act(() => { vi.advanceTimersByTime(1) })
    expect(fresh.current).toBe(false)
    // A capture already older than that is never offered.
    expect(captureOf(result('2026-11-23T09:40:00Z', false), LATEST, null).open).toBe(false)
  })
})
