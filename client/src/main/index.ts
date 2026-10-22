// The client's main process (H4, H26): one window, the bridge to the local server, Electron's security.
import { join } from 'node:path'
import { app, BrowserWindow, nativeTheme, session } from 'electron'
import { registerBridge } from './bridge'
import { confine, denyPermissions, webPreferences } from './window'

// During development the server runs on its own (`python -m mbs serve`); its address can be overridden.
const SERVER_URL = process.env.MBS_SERVER_URL ?? 'http://127.0.0.1:55433'

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    title: 'מערכת הזיהוי',
    autoHideMenuBar: true,
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#16181d' : '#f6f7f9',
    webPreferences: webPreferences(join(import.meta.dirname, '../preload/index.cjs')),
  })
  window.once('ready-to-show', () => window.show())
  const devServer = process.env.ELECTRON_RENDERER_URL
  if (devServer) void window.loadURL(devServer)
  else void window.loadFile(join(import.meta.dirname, '../renderer/index.html'))
}

app.on('web-contents-created', (_event, contents) => confine(contents))

app.whenReady().then(() => {
  denyPermissions(session.defaultSession)
  registerBridge(SERVER_URL)
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
