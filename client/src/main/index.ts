// The client's main process (H4, H26): one window, the bridge to the local server, Electron's security, and
// the client's own links, which open the screen that resets a password (H32).
import { join, resolve } from 'node:path'
import { app, BrowserWindow, nativeTheme, session } from 'electron'
import { registerBridge } from './bridge'
import { watchDisplays } from './displays'
import { findResetLink, PROTOCOL, type ResetLink } from './links'
import type { ServerClient } from './server'
import { appPageMatcher, confine, permitMedia, webPreferences } from './window'

// During development the server runs on its own (`python -m mbs serve`); its address can be overridden.
const SERVER_URL = process.env.MBS_SERVER_URL ?? 'http://127.0.0.1:55433'

let mainWindow: BrowserWindow | null = null
let server: ServerClient | null = null
let waiting: ResetLink | null = null

function createWindow(): void {
  const created = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    title: 'Identification System',
    autoHideMenuBar: true,
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#16181d' : '#f6f7f9',
    webPreferences: webPreferences(join(import.meta.dirname, '../preload/index.cjs')),
  })
  created.once('ready-to-show', () => created.show())
  created.on('closed', () => {
    if (mainWindow === created) mainWindow = null
  })
  mainWindow = created
  const devServer = process.env.ELECTRON_RENDERER_URL
  if (devServer) void created.loadURL(devServer)
  else void created.loadFile(join(import.meta.dirname, '../renderer/index.html'))
}

// A link from the command line: the token goes to the server client, and the page is told that it came.
// A page that is still loading asks for it when it starts.
function openLink(args: readonly string[]): void {
  const link = findResetLink(args)
  if (link === null) return
  if (server === null) {
    waiting = link
    return
  }
  server.openLink(link)
  if (mainWindow !== null) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
    mainWindow.webContents.send('mbs:link')
  }
}

// Windows starts a second client for a link while one runs; the running one takes the link, and the second
// ends at once.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  // mbs:// links open this client, for the current Windows user only. During development Electron runs the
  // app from its folder, so the registered command names that folder too (Electron's deep link guide).
  const entry = process.argv[1]
  if (!process.defaultApp) app.setAsDefaultProtocolClient(PROTOCOL)
  else if (entry !== undefined) app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [resolve(entry)])

  app.on('second-instance', (_event, args) => openLink(args))
  app.on('web-contents-created', (_event, contents) => confine(contents))

  app.whenReady().then(() => {
    permitMedia(session.defaultSession, appPageMatcher(process.env.ELECTRON_RENDERER_URL)) // H48, H54
    watchDisplays()
    server = registerBridge(SERVER_URL)
    if (waiting !== null) server.openLink(waiting)
    openLink(process.argv)
    createWindow()
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
}
