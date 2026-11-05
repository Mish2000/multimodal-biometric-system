import { describe, expect, it, vi } from 'vitest'
import { ServerClient } from './server'

const BASE = 'http://127.0.0.1:55433'
const ID = '0b0f6b9e-3c55-4d0e-9a51-4f0f2a7f1c11'
const ACCOUNT = { id: ID, username: 'dana', email: 'dana@example.com', role: 'user', must_change_password: false, theme: 'system', language: 'en' }
const RESET_TOKEN = 'k3J9_xQ-2mZ8vB1nL0pR7sT4uW6yA5cD9eF2gH3iJ4k'

function reply(status: number, body?: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  })
}

function client() {
  const request = vi.fn<typeof fetch>()
  return { request, server: new ServerClient(BASE, request) }
}

function sent(request: ReturnType<typeof client>['request'], call: number) {
  const [url, init] = request.mock.calls[call] ?? []
  return { url, method: init?.method, headers: init?.headers as Record<string, string>, body: init?.body }
}

describe('ServerClient', () => {
  it('refuses routes outside the fixed list without asking the server', async () => {
    const { request, server } = client()
    for (const route of ['../../api/admin/accounts', 'constructor', 'toString', 42, undefined]) {
      expect(await server.call(route)).toEqual({ ok: false, status: 0, error: 'unknown_route' })
    }
    for (const id of ['not-an-id', `${ID}/../../x`, undefined]) {
      expect(await server.call('setStatus', { password: 'x', status: 'disabled' }, id)).toMatchObject({ error: 'unknown_route' })
    }
    expect(request).not.toHaveBeenCalled()
  })

  it('sends JSON to the route the name stands for', async () => {
    const { request, server } = client()
    request.mockResolvedValueOnce(reply(201, { account: ACCOUNT })).mockResolvedValueOnce(reply(204))
    await server.call('register', { username: 'dana' })
    expect(sent(request, 0)).toMatchObject({
      url: `${BASE}/api/register`,
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{"username":"dana"}',
    })
    expect(await server.call('setStatus', { password: 'x', status: 'disabled' }, ID)).toEqual({ ok: true, data: null })
    expect(sent(request, 1).url).toBe(`${BASE}/api/admin/accounts/${ID}/status`)
  })

  it('keeps the session token to itself', async () => {
    const { request, server } = client()
    request.mockResolvedValueOnce(reply(200, { token: 'secret-token', account: ACCOUNT }))
    request.mockResolvedValueOnce(reply(200, { account: ACCOUNT, modalities: null }))
    const signedIn = await server.call('login', { login: 'dana', password: 'a long password' })
    expect(signedIn).toEqual({ ok: true, data: { account: ACCOUNT } })
    expect(JSON.stringify(signedIn)).not.toContain('secret-token')
    expect(sent(request, 0).headers.authorization).toBeUndefined()
    await server.call('me')
    expect(sent(request, 1).headers.authorization).toBe('Bearer secret-token')
  })

  it('forgets the token when the server has ended the session', async () => {
    const { request, server } = client()
    request.mockResolvedValueOnce(reply(200, { token: 'secret-token', account: ACCOUNT }))
    request.mockResolvedValueOnce(reply(401, { error: 'not_signed_in' }))
    request.mockResolvedValueOnce(reply(401, { error: 'not_signed_in' }))
    await server.call('login', { login: 'dana', password: 'a long password' })
    expect(await server.call('me')).toEqual({ ok: false, status: 401, error: 'not_signed_in' })
    expect(server.signedIn).toBe(false)
    await server.call('me')
    expect(sent(request, 2).headers.authorization).toBeUndefined()
  })

  it('signs out here even when the server cannot be reached', async () => {
    const { request, server } = client()
    expect(await server.call('logout')).toEqual({ ok: true, data: null })
    expect(request).not.toHaveBeenCalled()
    request.mockResolvedValueOnce(reply(200, { token: 'secret-token', account: ACCOUNT }))
    request.mockRejectedValueOnce(new TypeError('fetch failed'))
    await server.call('login', { login: 'dana', password: 'a long password' })
    expect(await server.call('logout')).toMatchObject({ ok: false, error: 'server_unreachable' })
    expect(server.signedIn).toBe(false)
  })

  it("adds a reset link's token to the reset routes, and the page learns only that the link came (H32)", async () => {
    const { request, server } = client()
    expect(await server.call('checkResetLink')).toEqual({ ok: false, status: 0, error: 'invalid_reset_link' })
    expect(request).not.toHaveBeenCalled()
    server.openLink({ token: RESET_TOKEN, language: 'he' })
    expect(server.takeLink()).toEqual({ kind: 'reset-password', language: 'he' })
    expect(server.takeLink()).toBeNull()
    request.mockResolvedValueOnce(reply(204)).mockResolvedValueOnce(reply(204))
    expect(await server.call('checkResetLink')).toEqual({ ok: true, data: null })
    expect(sent(request, 0)).toMatchObject({ url: `${BASE}/api/password-reset/check`, body: JSON.stringify({ token: RESET_TOKEN }) })
    await server.call('completeReset', { password: 'A new one 2027', token: 'from the page' })
    expect(sent(request, 1).body).toBe(JSON.stringify({ password: 'A new one 2027', token: RESET_TOKEN }))
    // A link works once: after the new password the token is gone.
    expect(await server.call('completeReset', { password: 'A new one 2027' })).toMatchObject({ error: 'invalid_reset_link' })
    expect(request).toHaveBeenCalledTimes(2)
  })

  it("passes the server's error codes on and names its own", async () => {
    const { request, server } = client()
    request.mockResolvedValueOnce(reply(409, { error: 'username_taken' }))
    request.mockResolvedValueOnce(reply(422, { detail: [{ loc: ['body', 'email'] }] }))
    request.mockResolvedValueOnce(reply(429, { error: 'too_many_attempts' }, { 'retry-after': '31' }))
    request.mockResolvedValueOnce(new Response('Internal Server Error', { status: 500 }))
    request.mockRejectedValueOnce(new TypeError('fetch failed'))
    expect(await server.call('register', {})).toEqual({ ok: false, status: 409, error: 'username_taken' })
    expect(await server.call('register', {})).toEqual({ ok: false, status: 422, error: 'invalid_request' })
    expect(await server.call('login', {})).toEqual({ ok: false, status: 429, error: 'too_many_attempts', retryAfter: 31 })
    expect(await server.call('health')).toEqual({ ok: false, status: 500, error: 'unexpected' })
    expect(await server.call('health')).toEqual({ ok: false, status: 0, error: 'server_unreachable' })
  })
})

// The enrolment's stream of JSON lines (H33), as the server sends it: in pieces that need not end at a line.
function streamed(pieces: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece))
      controller.close()
    },
  })
  return new Response(body, { status, headers: { 'content-type': 'application/x-ndjson' } })
}

describe('ServerClient fingerprint enrolment (H33)', () => {
  async function signedIn() {
    const { request, server } = client()
    request.mockResolvedValueOnce(reply(200, { token: 'session-token', account: ACCOUNT }))
    await server.call('login', { login: 'dana', password: 'a long password' })
    return { request, server }
  }

  it('passes on every event as it comes, with the session token, and ends with the last one', async () => {
    const { request, server } = await signedIn()
    const big = 'x'.repeat(200_000)
    request.mockResolvedValueOnce(
      streamed(['{"type":"started","finger":7}\n{"type":"pla', 'ce","placement":1}\n', `{"type":"saved","view":"${big.slice(0, 100_000)}`, `${big.slice(100_000)}"}\n`]),
    )
    const events: Array<{ type: string }> = []
    expect(await server.enrol(7, (event) => events.push(event as { type: string }))).toEqual({ ok: true, data: null })
    expect(events.map((e) => e.type)).toEqual(['started', 'place', 'saved'])
    expect((events[2] as unknown as { view: string }).view).toHaveLength(200_000)
    const { url, method, headers, body } = sent(request, 1)
    expect([url, method, body]).toEqual([`${BASE}/api/fingerprint/enrolments`, 'POST', '{"finger":7}'])
    expect(headers.authorization).toBe('Bearer session-token')
  })

  it("returns the server's refusal before any event, and checks the finger first", async () => {
    const { request, server } = await signedIn()
    const events: unknown[] = []
    for (const finger of [0, 11, 2.5, '7', undefined]) {
      expect(await server.enrol(finger, (e) => events.push(e))).toEqual({ ok: false, status: 0, error: 'invalid_request' })
    }
    request.mockResolvedValueOnce(reply(503, { error: 'fingerprint_unavailable' }))
    expect(await server.enrol(7, (e) => events.push(e))).toEqual({ ok: false, status: 503, error: 'fingerprint_unavailable' })
    expect(events).toEqual([])
  })

  it('tells the page when the stream ends early or is cancelled', async () => {
    const { request, server } = await signedIn()
    request.mockResolvedValueOnce(streamed(['{"type":"started","finger":7}\n']))
    const events: Array<{ type: string; error?: string }> = []
    await server.enrol(7, (e) => events.push(e as { type: string }))
    expect(events.at(-1)).toEqual({ type: 'failed', error: 'server_unreachable' })
    request.mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const running = server.enrol(7, (e) => events.push(e as { type: string }))
    expect(await server.enrol(7, () => undefined)).toEqual({ ok: false, status: 409, error: 'scanner_busy' })
    server.cancelEnrolment()
    expect(await running).toEqual({ ok: true, data: null })
  })
})

describe('ServerClient finger routes (H34)', () => {
  it('puts a finger position, 1 to 10, into the path and nothing else', async () => {
    const { request, server } = client()
    for (const id of ['0', '11', 'x', '7/../../admin', '07', undefined]) {
      expect(await server.call('deleteFingerprint', undefined, id)).toEqual({ ok: false, status: 0, error: 'unknown_route' })
    }
    expect(request).not.toHaveBeenCalled()
    request.mockResolvedValueOnce(reply(204))
    expect(await server.call('deleteFingerprint', undefined, '10')).toEqual({ ok: true, data: null })
    expect(sent(request, 0)).toMatchObject({ url: `${BASE}/api/fingerprint/fingers/10`, method: 'DELETE' })
  })
})
