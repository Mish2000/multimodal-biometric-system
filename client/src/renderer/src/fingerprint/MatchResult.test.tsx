// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MatchViewData, VerificationResult } from '../../../shared/bridge'
import { TEXTS } from '../texts'

// jsdom draws nothing, so the stage is a stand-in that the tests drive as the real one drives the screen.
const stages = vi.hoisted(() => ({ made: [] as Array<{
  input: { pairs: Float32Array; threshold: number }
  options: { reduced: boolean; onChange: (state: { count: number; verdict: boolean; done: boolean }) => void }
  running: boolean
  play: ReturnType<typeof vi.fn>
  finish: ReturnType<typeof vi.fn>
  select: ReturnType<typeof vi.fn>
  pick: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
  setColors: ReturnType<typeof vi.fn>
}>, decode: vi.fn(async () => ({}) as HTMLImageElement) }))

vi.mock('./stage', () => ({
  stageSupported: () => true,
  decodeCapture: stages.decode,
  MatchStage: class {
    running = true
    play = vi.fn()
    finish = vi.fn(() => this.running)
    select = vi.fn()
    pick = vi.fn(() => 2)
    dispose = vi.fn()
    setColors = vi.fn()
    constructor(_canvas: HTMLCanvasElement, readonly input: never, _colors: unknown, readonly options: never) {
      stages.made.push(this as never)
    }
  },
}))
vi.mock('../session', () => ({ useSession: () => ({ t: TEXTS.en, language: 'en' }) }))

const { MatchResult } = await import('./MatchResult')

function encoded(rows: number[][]): string {
  const bytes = new Uint8Array(new Float32Array(rows.flat()).buffer)
  return btoa(String.fromCharCode(...bytes))
}
const ROWS = [[100, 200, 110, 210], [300, 400, 310, 410], [500, 600, 510, 610]]
const view: MatchViewData = { placement: 2, reference_image: 'c3RvcmVk', count: 3, pairs: encoded(ROWS) }
const result = (accepted: boolean): VerificationResult => ({
  attempt_id: 'a1', at: '2026-11-15T10:00:00Z', finger: 7, algorithm: 'opencv-sift', score: 3, threshold: accepted ? 2 : 57,
  threshold_origin: 'test', accepted, duration_ms: 410, comparisons: [],
})

async function shown(accepted = true) {
  const rendered = render(<MatchResult result={result(accepted)} view={view} image="bmV3" />)
  await act(async () => { await Promise.resolve() })
  return { ...rendered, stage: stages.made.at(-1)! }
}

beforeEach(() => {
  stages.made.length = 0
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('pointer: fine'), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('the result of a fingerprint 1:1 verification on its stage (H22)', () => {
  it('gives the stage both captures and the counted pairs, and plays the moment once', async () => {
    const { stage } = await shown()
    expect(stages.decode.mock.calls.slice(-2)).toEqual([['bmV3'], ['c3RvcmVk']])
    expect(Array.from(stage.input.pairs)).toEqual(ROWS.flat())
    expect(stage.input.threshold).toBe(2)
    expect(stage.play).toHaveBeenCalledTimes(1)
  })

  it('holds the verdict back until the count decides it, while the count and the rail follow the threads', async () => {
    const { stage, container } = await shown()
    const heading = screen.getByRole('heading', { name: 'Fingerprint matches' })
    expect(heading.className).toBe('')
    expect(container.querySelector('.match-count strong')!.textContent).toBe('0')
    act(() => stage.options.onChange({ count: 2, verdict: false, done: false }))
    expect(container.querySelector('.match-count strong')!.textContent).toBe('2')
    expect((container.querySelector('.match-groove i') as HTMLElement).style.transform).toBe(`scaleX(${2 / (3 * 1.12)})`)
    expect(heading.className).toBe('')
    act(() => stage.options.onChange({ count: 3, verdict: true, done: false }))
    expect(heading.className).toBe('shown')
    expect(container.querySelector('.match-pair')!.textContent).toBe('')
  })

  it('says a non-match in the same plain words, with the threshold on the rail', async () => {
    const { stage, container } = await shown(false)
    act(() => stage.options.onChange({ count: 3, verdict: true, done: true }))
    expect(screen.getByRole('heading', { name: 'Fingerprint does not match' }).className).toBe('shown')
    expect(screen.getByText('Match above 57')).toBeTruthy()
    expect((container.querySelector('.match-groove i') as HTMLElement).style.transform).toBe(`scaleX(${3 / (57 * 1.12)})`)
  })

  it('lets a press play out the rest at once, and follows one pair by the keys and the pointer afterwards', async () => {
    const { stage, container } = await shown()
    const group = screen.getByRole('group', { name: 'The two captures and the pairs between them' })
    fireEvent.keyDown(group, { key: 'ArrowRight' })
    expect(stage.finish).toHaveBeenCalledTimes(1)
    expect(stage.select).not.toHaveBeenCalled()
    stage.running = false
    act(() => stage.options.onChange({ count: 3, verdict: true, done: true }))
    expect(container.querySelector('.match-pair')!.textContent).toBe('Move over a print, or use the arrow keys, to follow one pair.')
    fireEvent.keyDown(group, { key: 'ArrowLeft' })
    expect(stage.select).toHaveBeenLastCalledWith(2)
    expect(container.querySelector('.match-pair')!.textContent).toBe('Pair 3 of 3: new (500, 600), stored (510, 610)')
    fireEvent.keyDown(group, { key: 'ArrowRight' })
    expect(stage.select).toHaveBeenLastCalledWith(0)
    fireEvent.pointerMove(group, { clientX: 10, clientY: 10 })
    expect(stage.select).toHaveBeenLastCalledWith(2)
    fireEvent.pointerLeave(group)
    expect(stage.select).toHaveBeenLastCalledWith(-1)
  })

  it('lets go of the stage when the screen leaves', async () => {
    const { stage, unmount } = await shown()
    unmount()
    expect(stage.dispose).toHaveBeenCalledTimes(1)
  })

  it('draws the comparison flat, with the verdict at once, when the stage cannot be made', async () => {
    stages.decode.mockRejectedValueOnce(new Error('no image'))
    const { container } = await shown()
    expect(screen.getByRole('heading', { name: 'Fingerprint matches' })).toBeTruthy()
    expect(container.querySelector('.match-drawing')).not.toBeNull()
    expect(container.querySelector('.match-stage')).toBeNull()
  })
})
