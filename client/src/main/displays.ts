// H48: the laptop's lid, as the main process sees it. With the lid closed and external monitors in use,
// Windows turns the built-in screen off, so no display is internal, and the built-in camera sees only the
// inside of the lid. The page uses this to prefer another camera; the camera's own frames still decide.
import { BrowserWindow, screen } from 'electron'
import type { DisplayState } from '../shared/bridge'

export function displayState(): DisplayState {
  return { internalDisplay: screen.getAllDisplays().some((display) => display.internal) }
}

// Every window hears when the built-in screen comes or goes (the lid opened or closed).
export function watchDisplays(): void {
  let last = displayState().internalDisplay
  const update = () => {
    const state = displayState()
    if (state.internalDisplay === last) return
    last = state.internalDisplay
    for (const window of BrowserWindow.getAllWindows()) window.webContents.send('mbs:displays', state)
  }
  screen.on('display-added', update)
  screen.on('display-removed', update)
  screen.on('display-metrics-changed', update)
}
