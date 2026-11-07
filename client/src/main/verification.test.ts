import { describe, expect, it, vi } from 'vitest'
import { ServerClient } from './server'

const BASE = 'http://127.0.0.1:55433'
const RUN = '00000000-0000-4000-8000-000000000001'

describe('verification transport (H35)', () => {
  it.each(['pore-sift', 'learned-pore'])('sends %s on the fixed verification route and rejects unsupported methods (H38, H39)', async (algorithm) => {
    const request = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response('{"type":"failed","error":"no_finger"}\n'))
    const server = new ServerClient(BASE, request)
    expect(await server.verify(7, RUN, () => undefined, 'fusion')).toMatchObject({ error: 'invalid_request' })
    expect(request).not.toHaveBeenCalled()
    await server.verify(7, RUN, () => undefined, algorithm)
    expect(request.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ finger: 7, algorithm }))
  })
  it('allows only a valid finger and run id', async () => {
    const request = vi.fn<typeof fetch>()
    const server = new ServerClient(BASE, request)
    for (const finger of [0, 11, 1.5, '7', null]) {
      expect(await server.verify(finger, RUN, () => undefined)).toMatchObject({ ok: false, error: 'invalid_request' })
    }
    expect(await server.verify(7, '../x', () => undefined)).toMatchObject({ ok: false, error: 'invalid_request' })
    expect(request).not.toHaveBeenCalled()
  })

  it('uses the fixed authenticated route and finishes on the result even before EOF', async () => {
    const cancel = vi.fn()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"type":"veri'))
        controller.enqueue(new TextEncoder().encode('fied","score":88}\n'))
      },
      cancel,
    })
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ token: 'private-token', account: { id: 'user' } }))
      .mockResolvedValueOnce(new Response(stream))
    const server = new ServerClient(BASE, request)
    await server.call('login', { login: 'user', password: 'password' })
    const events: unknown[] = []
    expect(await server.verify(7, RUN, (event) => events.push(event))).toEqual({ ok: true, data: null })
    expect(request.mock.calls[1]).toEqual([`${BASE}/api/fingerprint/verifications`, expect.objectContaining({
      method: 'POST', body: '{"finger":7}', headers: { 'content-type': 'application/json', authorization: 'Bearer private-token' },
    })])
    expect(events).toEqual([{ type: 'verified', score: 88 }])
    expect(cancel).toHaveBeenCalledOnce()
    request.mockResolvedValueOnce(new Response('{"type":"failed","error":"no_finger"}\n'))
    expect(await server.enrol(7, () => undefined)).toEqual({ ok: true, data: null })
  })

  it('shares scanner ownership with enrolment and cancels only the matching run before headers arrive', async () => {
    const request = vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const server = new ServerClient(BASE, request)
    const events: unknown[] = []
    const pending = server.verify(7, RUN, (event) => events.push(event))
    expect(await server.enrol(7, () => undefined)).toMatchObject({ error: 'scanner_busy' })
    expect(await server.verify(7, RUN, () => undefined)).toMatchObject({ error: 'scanner_busy' })
    server.cancelVerification('different-run')
    server.cancelEnrolment()
    expect(request.mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
    server.cancelVerification(RUN)
    await pending
    expect(events).toEqual([{ type: 'failed', error: 'cancelled' }])
  })

  it('reports a truncated response and forgets an expired session', async () => {
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ token: 'private-token', account: {} }))
      .mockResolvedValueOnce(new Response('{"type":"started"}\n{"type":'))
      .mockResolvedValueOnce(Response.json({ error: 'not_signed_in' }, { status: 401 }))
    const server = new ServerClient(BASE, request)
    await server.call('login')
    const events: unknown[] = []
    await server.verify(7, RUN, (event) => events.push(event))
    expect(events.at(-1)).toEqual({ type: 'failed', error: 'server_unreachable' })
    expect(await server.verify(7, RUN, () => undefined)).toEqual({ ok: false, status: 401, error: 'not_signed_in' })
    expect(server.signedIn).toBe(false)
  })

  it('signing out cancels a verification in progress', async () => {
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ token: 'private-token', account: {} }))
      .mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const server = new ServerClient(BASE, request)
    await server.call('login')
    const events: unknown[] = []
    const pending = server.verify(7, RUN, (event) => events.push(event))
    await server.call('logout')
    await pending
    expect(events).toEqual([{ type: 'failed', error: 'cancelled' }])
    expect(server.signedIn).toBe(false)
  })
})
