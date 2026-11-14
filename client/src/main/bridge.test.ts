// The bridge's fingerprint streams (H33, H35, H41): a capture's events go to the page that started it, the capture
// ends with that page, and only the window's own top frame may start or cancel one. Electron's IPC is replaced
// here by maps of the registered handlers; the server client and its streamed requests are the real ones.
import { EventEmitter } from 'node:events'
import { afterEach, describe, expect, it, vi } from 'vitest'

type Handler = (event: unknown, ...args: unknown[]) => unknown

const ipc = vi.hoisted(() => ({ handlers: new Map<string, Handler>(), listeners: new Map<string, Handler>() }))

vi.mock('electron', () => ({
  ipcMain: {
    handle: (channel: string, handler: Handler) => ipc.handlers.set(channel, handler),
    on: (channel: string, listener: Handler) => ipc.listeners.set(channel, listener),
  },
  nativeTheme: { themeSource: 'system' },
  BrowserWindow: { getAllWindows: () => [] },
  screen: { getAllDisplays: () => [], on: () => undefined },
}))

import { registerBridge } from './bridge'

const BASE = 'http://127.0.0.1:55433'
const RUN = '00000000-0000-4000-8000-000000000001'
const LIFECYCLE = ['destroyed', 'did-start-loading', 'render-process-gone'] as const

// A window's page: Electron's WebContents as the bridge uses it.
class Page extends EventEmitter {
  destroyed = false
  sent: unknown[][] = []

  isDestroyed(): boolean {
    return this.destroyed
  }

  send(...message: unknown[]): void {
    this.sent.push(message)
  }
}

interface Stream {
  name: string
  start: string
  args: unknown[]
  events: string
  run: string[] // the run id that a verification's or an identification's events carry
  cancel: string
}

const STREAMS: Stream[] = [
  { name: 'enrolment', start: 'mbs:enrol', args: [7], events: 'mbs:enrolment', run: [], cancel: 'mbs:enrol-cancel' },
  { name: 'verification', start: 'mbs:verify', args: [7, RUN, 'opencv-sift'], events: 'mbs:verification', run: [RUN], cancel: 'mbs:verify-cancel' },
  { name: 'identification', start: 'mbs:identify', args: [RUN, 'opencv-sift'], events: 'mbs:identification', run: [RUN], cancel: 'mbs:identify-cancel' },
]

const top = (page: Page) => ({ senderFrame: { parent: null }, sender: page })
const inner = (page: Page) => ({ senderFrame: { parent: {} }, sender: page })

function registered(map: Map<string, Handler>, channel: string): Handler {
  const found = map.get(channel)
  if (found === undefined) throw new Error(`nothing is registered for ${channel}`)
  return found
}

// A server that keeps the capture waiting for a finger until the request is aborted.
function waitingServer() {
  const signals: AbortSignal[] = []
  const request = vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    const signal = init?.signal
    if (!signal) throw new Error('a capture request without a signal')
    signals.push(signal)
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  }))
  vi.stubGlobal('fetch', request)
  registerBridge(BASE)
  return { request, signals }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe.each(STREAMS)('a fingerprint $name (H33, H35, H41)', (stream) => {
  it.each(LIFECYCLE)('is cancelled when its own page emits %s', async (lifecycle) => {
    const { request, signals } = waitingServer()
    const page = new Page()
    const other = new Page()
    const running = registered(ipc.handlers, stream.start)(top(page), ...stream.args)
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())
    other.emit(lifecycle)
    expect(signals[0]?.aborted).toBe(false)
    if (lifecycle === 'destroyed') page.destroyed = true
    page.emit(lifecycle)
    expect(await running).toEqual({ ok: true, data: null })
    expect(signals[0]?.aborted).toBe(true)
    // A page that is gone hears nothing; a page that reloads or lost its process may still be told.
    expect(page.sent).toEqual(lifecycle === 'destroyed' ? [] : [[stream.events, ...stream.run, { type: 'failed', error: 'cancelled' }]])
    for (const name of LIFECYCLE) expect(page.listenerCount(name)).toBe(0)
  })

  it('sends its events to its page and leaves no listeners when it ends', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('{"type":"failed","error":"no_finger"}\n')))
    registerBridge(BASE)
    const page = new Page()
    expect(await registered(ipc.handlers, stream.start)(top(page), ...stream.args)).toEqual({ ok: true, data: null })
    expect(page.sent).toEqual([[stream.events, ...stream.run, { type: 'failed', error: 'no_finger' }]])
    for (const name of LIFECYCLE) expect(page.listenerCount(name)).toBe(0)
  })

  it("is started and cancelled only from the window's top frame", async () => {
    const { request, signals } = waitingServer()
    const page = new Page()
    expect(await registered(ipc.handlers, stream.start)(inner(page), ...stream.args))
      .toEqual({ ok: false, status: 0, error: 'unknown_route' })
    expect(request).not.toHaveBeenCalled()
    for (const name of LIFECYCLE) expect(page.listenerCount(name)).toBe(0)
    const running = registered(ipc.handlers, stream.start)(top(page), ...stream.args)
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())
    registered(ipc.listeners, stream.cancel)(inner(page), ...stream.run)
    expect(signals[0]?.aborted).toBe(false)
    registered(ipc.listeners, stream.cancel)(top(page), ...stream.run)
    expect(await running).toEqual({ ok: true, data: null })
    expect(signals[0]?.aborted).toBe(true)
  })
})
