// A change of theme (H24) flips prefers-color-scheme, and with it every colour of the page at once. The controls that
// ease their colours (buttons, fields, rails) would follow 150 ms late, so the change would show in two stages. For
// that moment the root carries `theme-changing`, under which nothing eases (styles.css); it comes off two frames
// later, once the new colours are painted.
type Frame = (callback: () => void) => number

export const CHANGING = 'theme-changing'

export function holdTransitionsOnThemeChange(scheme: MediaQueryList, root: HTMLElement, frame: Frame): () => void {
  const changed = () => {
    root.classList.add(CHANGING)
    frame(() => frame(() => root.classList.remove(CHANGING)))
  }
  scheme.addEventListener('change', changed)
  return () => scheme.removeEventListener('change', changed)
}
