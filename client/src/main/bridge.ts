// The page's only way to the server, to the window's theme and to the links that opened the client (H24,
// H26, H32). Requests come only from the window's own top frame, name a route from the fixed list, and are
// made here.
import { ipcMain, nativeTheme, type IpcMainEvent, type IpcMainInvokeEvent, type WebContents } from 'electron'
import { THEMES, type ApiResult, type Theme } from '../shared/bridge'
import { displayState } from './displays'
import { ServerClient } from './server'

function fromTopFrame(event: IpcMainEvent | IpcMainInvokeEvent): boolean {
  const frame = event.senderFrame
  return frame !== null && frame.parent === null
}

// A fingerprint capture (H33, H35, H41): its events go back to the page that started it, one by one, and the
// run ends with that page. When the page is destroyed, starts loading again or loses its process, the run is
// cancelled, so the server stops the scanner and the next run does not find it busy.
function stream(
  page: WebContents,
  cancel: () => void,
  send: (event: unknown) => void,
  start: (emit: (event: unknown) => void) => Promise<ApiResult>,
): Promise<ApiResult> {
  page.once('destroyed', cancel)
  page.once('did-start-loading', cancel)
  page.once('render-process-gone', cancel)
  return start((event) => {
    if (!page.isDestroyed()) send(event)
  }).finally(() => {
    page.removeListener('destroyed', cancel)
    page.removeListener('did-start-loading', cancel)
    page.removeListener('render-process-gone', cancel)
  })
}

export function registerBridge(serverUrl: string): ServerClient {
  const server = new ServerClient(serverUrl)
  ipcMain.handle('mbs:call', (event, route: unknown, body: unknown, id: unknown) =>
    fromTopFrame(event) ? server.call(route, body, id) : { ok: false, status: 0, error: 'unknown_route' },
  )
  // Before anyone signs in the window follows Windows' setting; after it, the account's choice.
  ipcMain.on('mbs:theme', (event, theme: unknown) => {
    if (fromTopFrame(event) && THEMES.includes(theme as Theme)) nativeTheme.themeSource = theme as Theme
  })
  // The page asks when it starts and whenever the main process says that a link came ('mbs:link').
  ipcMain.handle('mbs:take-link', (event) => (fromTopFrame(event) ? server.takeLink() : null))
  // H48: whether the built-in screen is on; changes reach the page as 'mbs:displays'.
  ipcMain.handle('mbs:displays', (event) => (fromTopFrame(event) ? displayState() : null))
  // A fingerprint enrolment (H33): one at a time, so its events carry no run.
  ipcMain.handle('mbs:enrol', (event, finger: unknown) => {
    if (!fromTopFrame(event)) return { ok: false, status: 0, error: 'unknown_route' }
    const page = event.sender
    return stream(
      page,
      () => server.cancelEnrolment(),
      (enrolmentEvent) => page.send('mbs:enrolment', enrolmentEvent),
      (emit) => server.enrol(finger, emit),
    )
  })
  ipcMain.on('mbs:enrol-cancel', (event) => {
    if (fromTopFrame(event)) server.cancelEnrolment()
  })
  // H35: a verification's events name their run, and only that run is cancelled.
  ipcMain.handle('mbs:verify', (event, finger: unknown, runId: unknown, algorithm: unknown) => {
    if (!fromTopFrame(event)) return { ok: false, status: 0, error: 'unknown_route' }
    const page = event.sender
    return stream(
      page,
      () => server.cancelVerification(runId),
      (verificationEvent) => page.send('mbs:verification', runId, verificationEvent),
      (emit) => server.verify(finger, runId, emit, algorithm),
    )
  })
  ipcMain.on('mbs:verify-cancel', (event, runId: unknown) => {
    if (fromTopFrame(event)) server.cancelVerification(runId)
  })
  // H41: identification has its own fixed route and per-run events, with the same window lifecycle.
  ipcMain.handle('mbs:identify', (event, runId: unknown, algorithm: unknown) => {
    if (!fromTopFrame(event)) return { ok: false, status: 0, error: 'unknown_route' }
    const page = event.sender
    return stream(
      page,
      () => server.cancelIdentification(runId),
      (identificationEvent) => page.send('mbs:identification', runId, identificationEvent),
      (emit) => server.identify(runId, emit, algorithm),
    )
  })
  ipcMain.on('mbs:identify-cancel', (event, runId: unknown) => {
    if (fromTopFrame(event)) server.cancelIdentification(runId)
  })
  return server
}
