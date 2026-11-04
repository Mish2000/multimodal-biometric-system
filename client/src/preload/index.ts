// The page's narrow window to the main process (H26): named server routes, the theme and the links that
// opened the client (H32), nothing else.
import { contextBridge, ipcRenderer } from 'electron'
import type { MbsBridge } from '../shared/bridge'

const bridge: MbsBridge = {
  call: (route, body, id) => ipcRenderer.invoke('mbs:call', route, body, id),
  setTheme: (theme) => ipcRenderer.send('mbs:theme', theme),
  takeLink: () => ipcRenderer.invoke('mbs:take-link'),
  onLink: (listener) => {
    const notify = () => listener()
    ipcRenderer.on('mbs:link', notify)
    return () => {
      ipcRenderer.removeListener('mbs:link', notify)
    }
  },
}

contextBridge.exposeInMainWorld('mbs', bridge)
