// The page's narrow window to the main process (H26): named server routes, the theme and the links that
// opened the client (H32), nothing else.
import { contextBridge, ipcRenderer } from 'electron'
import type { MbsBridge } from '../shared/bridge'

const bridge: MbsBridge = {
  call: (route, body, id) => ipcRenderer.invoke('mbs:call', route, body, id),
  setTheme: (theme) => ipcRenderer.send('mbs:theme', theme),
  takeLink: () => ipcRenderer.invoke('mbs:take-link'),
  displays: () => ipcRenderer.invoke('mbs:displays'),
  onDisplays: (listener) => {
    const pass = (_event: unknown, state: Parameters<typeof listener>[0]) => listener(state)
    ipcRenderer.on('mbs:displays', pass)
    return () => {
      ipcRenderer.removeListener('mbs:displays', pass)
    }
  },
  onLink: (listener) => {
    const notify = () => listener()
    ipcRenderer.on('mbs:link', notify)
    return () => {
      ipcRenderer.removeListener('mbs:link', notify)
    }
  },
  enrolFingerprint: (finger) => ipcRenderer.invoke('mbs:enrol', finger),
  cancelEnrolment: () => ipcRenderer.send('mbs:enrol-cancel'),
  onEnrolment: (listener) => {
    const pass = (_event: unknown, enrolmentEvent: Parameters<typeof listener>[0]) => listener(enrolmentEvent)
    ipcRenderer.on('mbs:enrolment', pass)
    return () => {
      ipcRenderer.removeListener('mbs:enrolment', pass)
    }
  },
  verifyFingerprint: (finger, runId, algorithm) => ipcRenderer.invoke('mbs:verify', finger, runId, algorithm),
  cancelVerification: (runId) => ipcRenderer.send('mbs:verify-cancel', runId),
  onVerification: (runId, listener) => {
    const pass = (_event: unknown, receivedId: string, verificationEvent: Parameters<typeof listener>[0]) => {
      if (receivedId === runId) listener(verificationEvent)
    }
    ipcRenderer.on('mbs:verification', pass)
    return () => {
      ipcRenderer.removeListener('mbs:verification', pass)
    }
  },
  identifyFingerprint: (runId, algorithm) => ipcRenderer.invoke('mbs:identify', runId, algorithm),
  cancelIdentification: (runId) => ipcRenderer.send('mbs:identify-cancel', runId),
  onIdentification: (runId, listener) => {
    const pass = (_event: unknown, receivedId: string, identificationEvent: Parameters<typeof listener>[0]) => {
      if (receivedId === runId) listener(identificationEvent)
    }
    ipcRenderer.on('mbs:identification', pass)
    return () => { ipcRenderer.removeListener('mbs:identification', pass) }
  },
}

contextBridge.exposeInMainWorld('mbs', bridge)
