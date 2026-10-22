import { describe, expect, it, vi } from 'vitest'
import { ServerClient } from './server'

const BASE = 'http://127.0.0.1:55433'
const ID = '0b0f6b9e-3c55-4d0e-9a51-4f0f2a7f1c11'
const ACCOUNT = { id: ID, username: 'dana', email: 'dana@example.com', role: 'user', must_change_password: false, theme: 'system' }

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
