/// <reference types="vite/client" />
import type { MbsBridge } from '../../shared/bridge'

declare global {
  interface Window {
    mbs: MbsBridge
  }
}

export {}
