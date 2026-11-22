// @vitest-environment jsdom
// A change of theme repaints every colour at once (H24): the controls' own eases are held for that moment.
import { describe, expect, it } from 'vitest'
import { CHANGING, holdTransitionsOnThemeChange } from './themeChange'

// jsdom has no matchMedia: a media query list is an event target that says when it changes.
function scheme(): MediaQueryList {
  return new EventTarget() as MediaQueryList
}

function frames(): { frame: (callback: () => void) => number; next: () => void } {
  let queue: Array<() => void> = []
  return {
    frame: (callback) => queue.push(callback),
    next: () => {
      const due = queue
      queue = []
      due.forEach((callback) => callback())
    },
  }
}

describe('a change of theme', () => {
  it('holds every transition until the new colours have been painted', () => {
    const media = scheme()
    const root = document.createElement('html')
    const clock = frames()
    holdTransitionsOnThemeChange(media, root, clock.frame)

    media.dispatchEvent(new Event('change'))
    expect(root.classList.contains(CHANGING)).toBe(true)
    clock.next()
    expect(root.classList.contains(CHANGING)).toBe(true)
    clock.next()
    expect(root.classList.contains(CHANGING)).toBe(false)
  })

  it('stops listening once released', () => {
    const media = scheme()
    const root = document.createElement('html')
    const release = holdTransitionsOnThemeChange(media, root, frames().frame)

    release()
    media.dispatchEvent(new Event('change'))
    expect(root.classList.contains(CHANGING)).toBe(false)
  })
})
