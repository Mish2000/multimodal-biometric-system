// The page's only way to the server, to the window's theme and to the links that opened the client (H24,
// H26, H32). Requests come only from the window's own top frame, name a route from the fixed list, and are
// made here.
import { ipcMain, nativeTheme, type IpcMainEvent, type IpcMainInvokeEvent } from 'electron'
import { THEMES, type Theme } from '../shared/bridge'
import { displayState } from './displays'
import { ServerClient } from './server'

function fromTopFrame(event: IpcMainEvent | IpcMainInvokeEvent): boolean {
  const frame = event.senderFrame
  return frame !== null && frame.parent === null
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
  // A fingerprint enrolment (H33): its events go back to the page that started it, one by one.
  ipcMain.handle('mbs:enrol', (event, finger: unknown) => {
    if (!fromTopFrame(event)) return { ok: false, status: 0, error: 'unknown_route' }
    const page = event.sender
    return server.enrol(finger, (enrolmentEvent) => {
      if (!page.isDestroyed()) page.send('mbs:enrolment', enrolmentEvent)
    })
  })
  ipcMain.on('mbs:enrol-cancel', (event) => {
    if (fromTopFrame(event)) server.cancelEnrolment()
  })
  ipcMain.handle('mbs:verify', (event, finger: unknown, runId: unknown, algorithm: unknown) => {
    if (!fromTopFrame(event)) return { ok: false, status: 0, error: 'unknown_route' }
    const page = event.sender
    const cancel = () => server.cancelVerification(runId)
    page.once('destroyed', cancel)
    page.once('did-start-loading', cancel)
    page.once('render-process-gone', cancel)
    return server.verify(finger, runId, (verificationEvent) => {
      if (!page.isDestroyed()) page.send('mbs:verification', runId, verificationEvent)
    }, algorithm).finally(() => {
      page.removeListener('destroyed', cancel)
      page.removeListener('did-start-loading', cancel)
      page.removeListener('render-process-gone', cancel)
    })
  })
  ipcMain.on('mbs:verify-cancel', (event, runId: unknown) => {
    if (fromTopFrame(event)) server.cancelVerification(runId)
  })
  // H41: identification has its own fixed route and per-run events, with the same window lifecycle.
  ipcMain.handle('mbs:identify', (event, runId: unknown, algorithm: unknown) => {
    if (!fromTopFrame(event)) return { ok: false, status: 0, error: 'unknown_route' }
    const page = event.sender
    const cancel = () => server.cancelIdentification(runId)
    page.once('destroyed', cancel)
    page.once('did-start-loading', cancel)
    page.once('render-process-gone', cancel)
    return server.identify(runId, (identificationEvent) => {
      if (!page.isDestroyed()) page.send('mbs:identification', runId, identificationEvent)
    }, algorithm).finally(() => {
      page.removeListener('destroyed', cancel)
      page.removeListener('did-start-loading', cancel)
      page.removeListener('render-process-gone', cancel)
    })
  })
  ipcMain.on('mbs:identify-cancel', (event, runId: unknown) => {
    if (fromTopFrame(event)) server.cancelIdentification(runId)
  })
  return server
}
