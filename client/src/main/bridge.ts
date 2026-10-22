// The page's only way to the server and to the window's theme (H24, H26). Requests come only from the
// window's own top frame, name a route from the fixed list, and are made here.
import { ipcMain, nativeTheme, type IpcMainEvent, type IpcMainInvokeEvent } from 'electron'
import { THEMES, type Theme } from '../shared/bridge'
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
  return server
}
