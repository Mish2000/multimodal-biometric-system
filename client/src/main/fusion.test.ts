import { describe, expect, it, vi } from 'vitest'
import { ServerClient } from './server'

const BASE = 'http://127.0.0.1:55433'
const RUN = '00000000-0000-4000-8000-000000000001'
const AT = '2026-11-23T12:00:00.000Z'

describe('combined test transport (H60)', () => {
  it('sends 1:1 with its finger and 1:N without one, each on its fixed route', async () => {
    const request = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{"type":"failed","error":"no_finger"}\n'))
    const server = new ServerClient(BASE, request)
    const voice = { recording: 'UklGRg==', captured_at: AT }
    await server.fuse('verify', RUN, 7, { voice }, () => undefined)
    await server.fuse('identify', RUN, null, { face: { image: 'iVBORw==', captured_at: AT } }, () => undefined)
    expect(request.mock.calls.map(([url]) => url)).toEqual([`${BASE}/api/fusion/verifications`, `${BASE}/api/fusion/identifications`])
    expect(request.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ finger: 7, voice }))
    expect(request.mock.calls[1]?.[1]?.body).toBe(JSON.stringify({ face: { image: 'iVBORw==', captured_at: AT } }))
  })

  it('refuses anything else before it reaches the server', async () => {
    const request = vi.fn<typeof fetch>()
    const server = new ServerClient(BASE, request)
    const voice = { recording: 'UklGRg==', captured_at: AT }
    const refused = [
      ['both', RUN, 7, { voice }], ['verify', '../x', 7, { voice }], ['verify', RUN, 11, { voice }],
      ['verify', RUN, null, { voice }], ['identify', RUN, 7, { voice }], ['verify', RUN, 7, null],
      ['verify', RUN, 7, { voice, fingerprint: {} }], ['verify', RUN, 7, { voice: { ...voice, name: 'a.wav' } }],
      ['verify', RUN, 7, { voice: { ...voice, recording: 'not base64!' } }],
      ['verify', RUN, 7, { voice: { ...voice, captured_at: 'yesterday' } }],
      ['verify', RUN, 7, { voice: { ...voice, recording: 'A'.repeat(1_400_000) } }],
    ] as const
    for (const [mode, runId, finger, samples] of refused) {
      expect(await server.fuse(mode, runId, finger, samples, () => undefined)).toMatchObject({ ok: false, error: 'invalid_request' })
    }
    expect(request).not.toHaveBeenCalled()
  })

  it('ends the stream on a refused sample, without reporting it as cut', async () => {
    const request = vi.fn<typeof fetch>().mockResolvedValueOnce(
      new Response('{"type":"started"}\n{"type":"sample_rejected","modality":"voice","checks":[]}\n'))
    const server = new ServerClient(BASE, request)
    const events: Array<{ type: string }> = []
    await server.fuse('verify', RUN, 7, { voice: { recording: 'UklGRg==', captured_at: AT } }, (event) => events.push(event as { type: string }))
    expect(events.map((event) => event.type)).toEqual(['started', 'sample_rejected'])
  })
})
