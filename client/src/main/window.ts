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
