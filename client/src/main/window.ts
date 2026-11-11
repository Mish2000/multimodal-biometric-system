// The window's security (H26), apart from the app's start so that an automated check can apply the same
// settings to a window that stays offscreen.
import type { Session, WebContents, WebPreferences } from 'electron'

// The page runs sandboxed, with no Node.js, and reaches the main process only through the preload's bridge.
export function webPreferences(preload: string): WebPreferences {
  return { preload, sandbox: true, contextIsolation: true, nodeIntegration: false, spellcheck: false }
}

// Every page shows only the app: links never navigate it away, and nothing opens other windows.
export function confine(contents: WebContents): void {
  contents.on('will-navigate', (event) => event.preventDefault())
  contents.setWindowOpenHandler(() => ({ action: 'deny' }))
}

// No permission (camera, microphone, notifications, ...) is granted until a modality needs one.
export function denyPermissions(session: Session): void {
  session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  session.setPermissionCheckHandler(() => false)
}

// H48: the face needs the camera, and (H54) the voice the microphone, each only for the app's own page. A request
// asks for the camera alone or the microphone alone, never both, and every other permission stays refused.
export function permitMedia(session: Session, appPage: (url: string) => boolean): void {
  session.setPermissionRequestHandler((contents, permission, callback, details) => {
    const types = (details as { mediaTypes?: string[] }).mediaTypes ?? []
    const url = (details as { requestingUrl?: string }).requestingUrl ?? contents.getURL()
    const one = types.length > 0 && (types.every((type) => type === 'video') || types.every((type) => type === 'audio'))
    callback(permission === 'media' && one && appPage(url))
  })
  session.setPermissionCheckHandler((_contents, permission, requestingOrigin, details) => {
    const type = (details as { mediaType?: string }).mediaType
    return permission === 'media' && (type === 'video' || type === 'audio') && appPage(requestingOrigin)
  })
}

// The app's page: its built files, or the development server's origin while developing.
export function appPageMatcher(devServer: string | undefined): (url: string) => boolean {
  if (!devServer) return (url) => url.startsWith('file://')
  const origin = new URL(devServer).origin
  return (url) => {
    try {
      return new URL(url).origin === origin
    } catch {
      return false
    }
  }
}
