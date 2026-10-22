// The page's narrow window to the main process (H26): named server routes and the theme, nothing else.
import { contextBridge, ipcRenderer } from 'electron'
import type { MbsBridge } from '../shared/bridge'

const bridge: MbsBridge = {
  call: (route, body, id) => ipcRenderer.invoke('mbs:call', route, body, id),
  setTheme: (theme) => ipcRenderer.send('mbs:theme', theme),
}

contextBridge.exposeInMainWorld('mbs', bridge)
