// @vitest-environment jsdom
// Light Table's components in the client (H22): what each says to assistive technology and how it marks its state.
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BUSY_AFTER_MS, Notice } from './Notice'
import { Plate } from './Plate'
import { railMaximum, ScoreMeter } from './ScoreMeter'
import { Steps } from './Steps'
import { Tag } from './Tag'

afterEach(cleanup)

describe('ScoreMeter', () => {
  it('runs a count to four times its threshold or a little beyond the score, and a similarity to 1', () => {
    expect(railMaximum(8, 57, 'count')).toBe(228)
    expect(railMaximum(614, 57, 'count')).toBeCloseTo(706.1)
    expect(railMaximum(0, 0, 'count')).toBe(1)
    expect(railMaximum(0.712, 0.363, 'similarity')).toBe(1)
  })

  it('gives screen readers the score itself, and draws the fill and the tick from the rail', () => {
    const { container } = render(
      <ScoreMeter score={614} threshold={57} scale="count" label="Matching points" thresholdLabel="Match above 57" accepted
        verdict={<h2>Fingerprint matches</h2>} explanation="The highest of the three scores is 614." />,
    )
    const meter = screen.getByRole('meter', { name: 'Matching points' }) as HTMLMeterElement
    expect(meter.value).toBe(614)
    expect(meter.max).toBeCloseTo(706.1)
    const score = container.querySelector<HTMLElement>('.score')!
    expect(score.className).toBe('score')
    expect(Number(score.style.getPropertyValue('--fill'))).toBeCloseTo(614 / 706.1)
    expect(Number(score.style.getPropertyValue('--at'))).toBeCloseTo(57 / 706.1)
    expect(screen.getByRole('heading', { name: 'Fingerprint matches' })).toBeTruthy()
    expect(screen.getByText('Match above 57')).toBeTruthy()
    expect(screen.getByText('The highest of the three scores is 614.')).toBeTruthy()
    // The drawn rail and its ends are decoration.
    expect(container.querySelector('.score-rail')!.getAttribute('aria-hidden')).toBe('true')
    expect(container.querySelector('.score-ends')!.getAttribute('aria-hidden')).toBe('true')
  })

  it('says a score at or below its threshold in ink, and ends a similarity at 1', () => {
    const { container } = render(
      <ScoreMeter score={0.301} threshold={0.363} scale="similarity" label="Similarity" shown="0.301"
        thresholdLabel="Match above 0.363" accepted={false} />,
    )
    expect(container.querySelector('.score')!.className).toBe('score below')
    expect(screen.getByText('0.301')).toBeTruthy()
    expect(container.querySelector('.score-max')!.textContent).toBe('1')
    expect((screen.getByRole('meter', { name: 'Similarity' }) as HTMLMeterElement).value).toBeCloseTo(0.301)
  })
})

describe('Notice', () => {
  it('carries its tone, takes the role it is given and says only its words', () => {
    render(<Notice tone="alert" role="alert">No finger was placed within a minute.</Notice>)
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toBe('No finger was placed within a minute.')
    expect(alert.getAttribute('data-tone')).toBe('alert')
    expect(alert.querySelector('.notice-mark')!.getAttribute('aria-hidden')).toBe('true')
  })

  it('shows the sensor’s dot only for a device capturing now, and a turning ring for work under way', () => {
    const { container, rerender } = render(<Notice tone="live">Place the finger.</Notice>)
    expect(container.querySelector('.live-dot')).not.toBeNull()
    rerender(<Notice tone="busy">Comparing…</Notice>)
    expect(container.querySelector('.live-dot')).toBeNull()
    expect(container.querySelector('.busy-ring')).not.toBeNull()
    rerender(<Notice>Context.</Notice>)
    expect(container.querySelector('.notice')!.getAttribute('data-tone')).toBe('info')
    expect(container.querySelector('[role]')).toBeNull()
  })

  it('names a confirmation and holds its actions', () => {
    render(
      <Notice tone="alert" role="alertdialog" label="Delete this finger’s enrolment" actions={<button type="button">Delete</button>}>
        <p>Delete the enrolment of the left index?</p>
      </Notice>,
    )
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this finger’s enrolment' })
    expect(dialog.textContent).toContain('Delete the enrolment of the left index?')
    expect(screen.getByRole('button', { name: 'Delete' }).closest('.actions')).not.toBeNull()
  })

  it('shows work under way only once it has lasted a moment, so a quick check never flashes', () => {
    vi.useFakeTimers()
    try {
      const { container, unmount } = render(<Notice tone="busy">Comparing…</Notice>)
      expect(container.querySelector('.notice')).toBeNull()
      act(() => { vi.advanceTimersByTime(BUSY_AFTER_MS - 1) })
      expect(container.querySelector('.notice')).toBeNull()
      act(() => { vi.advanceTimersByTime(1) })
      expect(container.querySelector('.busy-ring')).not.toBeNull()
      unmount()

      // A check that answers sooner leaves nothing behind.
      const quick = render(<Notice tone="busy">Comparing…</Notice>)
      quick.unmount()
      act(() => { vi.advanceTimersByTime(BUSY_AFTER_MS) })
      expect(document.querySelector('.notice')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('marks a notice that belongs to its screen, which then has no entrance of its own', () => {
    const { container, rerender } = render(<Notice still>Enrol this finger first.</Notice>)
    expect(container.querySelector('.notice')!.className).toBe('notice still')
    rerender(<Notice className="rejected">Too dark.</Notice>)
    expect(container.querySelector('.notice')!.className).toBe('notice rejected')
  })
})

describe('Steps', () => {
  it('marks the reached steps and the current one, which alone is the current step', () => {
    render(<Steps label="Fingerprint verification" steps={['Capture', 'Quality', 'Comparison', 'Result']} current={2}
      reached={(index) => index < 2} />)
    const items = screen.getAllByRole('listitem')
    expect(items.map((item) => item.getAttribute('data-state'))).toEqual(['done', 'done', 'current', 'todo'])
    expect(items.map((item) => item.getAttribute('aria-current'))).toEqual([null, null, 'step', null])
    expect(screen.getByRole('list', { name: 'Fingerprint verification' })).toBeTruthy()
  })

  it('has no current step once the flow has ended', () => {
    render(<Steps label="Fingerprint verification" steps={['Capture', 'Result']} current={-1} reached={() => true} />)
    expect(screen.getAllByRole('listitem').map((item) => item.getAttribute('data-state'))).toEqual(['done', 'done'])
  })
})

describe('Plate and Tag', () => {
  it('names a capture for assistive technology, and draws nothing where the page has no 2D canvas', () => {
    const { container } = render(<Plate image="c3RvcmVk" size={280} label="The new capture" state="rejected" />)
    expect(screen.getByRole('img', { name: 'The new capture' })).toBeTruthy()
    const plate = container.querySelector<HTMLElement>('.plate')!
    expect(plate.getAttribute('data-state')).toBe('rejected')
    expect(plate.getAttribute('data-drawn')).toBeNull()
    expect(plate.style.width).toBe('280px')
  })

  it('hides an unnamed plate, which is decoration', () => {
    const { container } = render(<Plate image="c3RvcmVk" size={96} />)
    expect(container.querySelector('canvas')!.getAttribute('aria-hidden')).toBe('true')
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('writes a state as a tag with its tone', () => {
    render(<Tag tone="ink">Highest score</Tag>)
    expect(screen.getByText('Highest score').getAttribute('data-tone')).toBe('ink')
  })
})
