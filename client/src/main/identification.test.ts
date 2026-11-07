import { describe, expect, it, vi } from 'vitest'
import { ServerClient } from './server'

const BASE = 'http://127.0.0.1:55433'
const RUN = '00000000-0000-4000-8000-000000000001'

describe('identification transport (H41)', () => {
  it.each(['opencv-sift', 'pore-sift', 'learned-pore'])('sends %s with authentication and finishes on identified before EOF', async (algorithm) => {
    const cancel = vi.fn()
    const stream = new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('{"type":"identified","score":90}\n')) },
      cancel,
    })
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ token: 'private-token', account: {} }))
      .mockResolvedValueOnce(new Response(stream))
    const server = new ServerClient(BASE, request)
    await server.call('login')
    const events: unknown[] = []
    expect(await server.identify(RUN, (event) => events.push(event), algorithm)).toEqual({ ok: true, data: null })
    expect(request.mock.calls[1]).toEqual([`${BASE}/api/fingerprint/identifications`, expect.objectContaining({
      method: 'POST', body: JSON.stringify({ algorithm }),
      headers: { 'content-type': 'application/json', authorization: 'Bearer private-token' },
    })])
    expect(events).toEqual([{ type: 'identified', score: 90 }])
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('shares the scanner with enrolment and verification, and only its own run can cancel it', async () => {
    const request = vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const server = new ServerClient(BASE, request)
    expect(await server.identify('../bad', () => undefined)).toMatchObject({ error: 'invalid_request' })
    expect(await server.identify(RUN, () => undefined, 'fusion')).toMatchObject({ error: 'invalid_request' })
    expect(request).not.toHaveBeenCalled()
    const events: unknown[] = []
    const pending = server.identify(RUN, (event) => events.push(event))
    expect(await server.enrol(7, () => undefined)).toMatchObject({ error: 'scanner_busy' })
    expect(await server.verify(7, RUN, () => undefined)).toMatchObject({ error: 'scanner_busy' })
    expect(await server.identify(RUN, () => undefined)).toMatchObject({ error: 'scanner_busy' })
    server.cancelIdentification('different-run')
    server.cancelVerification(RUN)
    server.cancelEnrolment()
    expect(request.mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
    server.cancelIdentification(RUN)
    await pending
    expect(events).toEqual([{ type: 'failed', error: 'cancelled' }])
  })

  it('reports an incomplete search stream and clears an expired session', async () => {
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ token: 'private-token', account: {} }))
      .mockResolvedValueOnce(new Response('{"type":"searching","completed":4,"total":9}\n'))
      .mockResolvedValueOnce(Response.json({ error: 'not_signed_in' }, { status: 401 }))
    const server = new ServerClient(BASE, request)
    await server.call('login')
    const events: unknown[] = []
    await server.identify(RUN, (event) => events.push(event))
    expect(events.at(-1)).toEqual({ type: 'failed', error: 'server_unreachable' })
    expect(await server.identify(RUN, () => undefined)).toMatchObject({ status: 401, error: 'not_signed_in' })
    expect(server.signedIn).toBe(false)
  })
})
