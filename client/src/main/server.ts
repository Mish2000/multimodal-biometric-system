// Requests to the local server on behalf of the page (H11, H26). The session token is kept here and is
// never handed to the page, so a script running in the page cannot read or send it elsewhere. The token of
// a link that opened the client to reset a password stays here in the same way (H32).
import { ROUTES, FINGERPRINT_ALGORITHMS, type ApiResult, type OpenedLink, type RouteName, type FingerprintAlgorithm } from '../shared/bridge'
import type { ResetLink } from './links'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const FINGER = /^(?:[1-9]|10)$/ // a finger's position (H34)
const TIMEOUT_MS = 15_000
const WITH_RESET_TOKEN: readonly RouteName[] = ['checkResetLink', 'completeReset']

export class ServerClient {
  private token: string | null = null
  private resetToken: string | null = null
  private opened: OpenedLink | null = null
  private capture: { controller: AbortController; path: string; runId: string | null } | null = null

  constructor(
    private readonly base: string,
    private readonly request: typeof fetch = fetch,
  ) {}

  get signedIn(): boolean {
    return this.token !== null
  }

  // A reset link that opened the client: its token waits here for the two reset routes, and the page
  // learns only that the link came, with its language. A newer link replaces an older one.
  openLink(link: ResetLink): void {
    this.resetToken = link.token
    this.opened = { kind: 'reset-password', language: link.language }
  }

  takeLink(): OpenedLink | null {
    const opened = this.opened
    this.opened = null
    return opened
  }

  async call(route: unknown, body?: unknown, id?: unknown): Promise<ApiResult> {
    if (typeof route !== 'string' || !Object.hasOwn(ROUTES, route)) return refused('unknown_route')
    const [method, template] = ROUTES[route as RouteName]
    let path: string = template
    if (template.includes('{id}')) {
      if (typeof id !== 'string' || !UUID.test(id)) return refused('unknown_route')
      path = template.replace('{id}', id)
    }
    if (template.includes('{finger}')) {
      if (typeof id !== 'string' || !FINGER.test(id)) return refused('unknown_route')
      path = template.replace('{finger}', id)
    }
    if (WITH_RESET_TOKEN.includes(route as RouteName)) {
      if (this.resetToken === null) return refused('invalid_reset_link')
      const sent = { ...(typeof body === 'object' && body !== null ? body : {}), token: this.resetToken }
      const result = await this.send(method, path, sent, null)
      if (result.ok && route === 'completeReset') this.resetToken = null
      return result
    }
    if (route === 'logout') {
      // Signing out ends the session here even when the server is gone or the session already expired.
      const token = this.token
      this.token = null
      this.cancelCapture()
      if (token === null) return { ok: true, data: null }
      return this.send(method, path, undefined, token)
    }
    const result = await this.send(method, path, body, this.token)
    if (!result.ok && result.status === 401 && route !== 'login') this.token = null
    if (result.ok && route === 'login') {
      const { token, account } = result.data as { token: string; account: unknown }
      this.token = token
      return { ok: true, data: { account } }
    }
    return result
  }

  // Fingerprint capture (H33, H35): the server's answer is a stream of JSON lines, passed on one event at a
  // time as they come. It has no overall time limit, since the scanner waits for the finger (the server
  // bounds every wait); cancelling closes the connection, and the server then stops the scanner.
  async enrol(finger: unknown, emit: (event: unknown) => void): Promise<ApiResult> {
    if (!validFinger(finger)) return refused('invalid_request')
    return this.scan(ENROLMENTS, { finger }, null, emit)
  }

  async verify(finger: unknown, runId: unknown, emit: (event: unknown) => void, algorithm?: unknown): Promise<ApiResult> {
    if (!validFinger(finger)) return refused('invalid_request')
    if (typeof runId !== 'string' || !UUID.test(runId)) return refused('invalid_request')
    if (algorithm !== undefined && !FINGERPRINT_ALGORITHMS.includes(algorithm as FingerprintAlgorithm)) return refused('invalid_request')
    return this.scan(VERIFICATIONS, { finger, ...(algorithm === undefined ? {} : { algorithm }) }, runId, emit)
  }

  async identify(runId: unknown, emit: (event: unknown) => void, algorithm: unknown = 'opencv-sift'): Promise<ApiResult> {
    if (typeof runId !== 'string' || !UUID.test(runId)) return refused('invalid_request')
    if (!FINGERPRINT_ALGORITHMS.includes(algorithm as FingerprintAlgorithm)) return refused('invalid_request')
    return this.scan(IDENTIFICATIONS, { algorithm }, runId, emit)
  }

  private async scan(path: string, body: object, runId: string | null, emit: (event: unknown) => void): Promise<ApiResult> {
    if (this.capture !== null) return { ok: false, status: 409, error: 'scanner_busy' }
    const controller = new AbortController()
    this.capture = { controller, path, runId }
    let ended = false
    const pass = (event: { type?: unknown; error?: unknown }) => {
      if (event.type === 'saved' || event.type === 'verified' || event.type === 'identified' || event.type === 'failed') {
        ended = true
        if (this.capture?.controller === controller) this.capture = null
      }
      emit(event)
      return ended
    }
    try {
      const headers: Record<string, string> = { 'content-type': 'application/json' }
      if (this.token !== null) headers.authorization = `Bearer ${this.token}`
      let response: Response
      try {
        response = await this.request(this.base + path, {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
          signal: controller.signal,
        })
      } catch {
        if (controller.signal.aborted) {
          pass({ type: 'failed', error: 'cancelled' })
          return { ok: true, data: null }
        }
        return refused('server_unreachable')
      }
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null)
        if (response.status === 401) this.token = null
        const code = (data as { error?: unknown } | null)?.error
        return { ok: false, status: response.status, error: typeof code === 'string' ? code : response.status === 422 ? 'invalid_request' : 'unexpected' }
      }
      try {
        await readLines(response, (line) => pass(JSON.parse(line) as { type?: unknown }))
      } catch {
        // A cut connection or a broken line: the page hears below that the enrolment did not finish.
      }
      if (!ended) pass({ type: 'failed', error: controller.signal.aborted ? 'cancelled' : 'server_unreachable' })
      return { ok: true, data: null }
    } finally {
      controller.abort()
      if (this.capture?.controller === controller) this.capture = null
    }
  }

  cancelEnrolment(): void {
    if (this.capture?.path === ENROLMENTS) this.cancelCapture()
  }

  cancelVerification(runId: unknown): void {
    if (this.capture?.path === VERIFICATIONS && this.capture.runId === runId) this.cancelCapture()
  }

  cancelIdentification(runId: unknown): void {
    if (this.capture?.path === IDENTIFICATIONS && this.capture.runId === runId) this.cancelCapture()
  }

  cancelCapture(): void {
    this.capture?.controller.abort()
  }

  private async send(method: string, path: string, body: unknown, token: string | null): Promise<ApiResult> {
    const headers: Record<string, string> = {}
    if (body !== undefined) headers['content-type'] = 'application/json'
    if (token !== null) headers.authorization = `Bearer ${token}`
    let response: Response
    try {
      response = await this.request(this.base + path, {
        method,
        headers,
        body: body === undefined ? null : JSON.stringify(body),
        signal: AbortSignal.timeout(TIMEOUT_MS),
      })
    } catch {
      return { ok: false, status: 0, error: 'server_unreachable' }
    }
    const data: unknown = response.status === 204 ? null : await response.json().catch(() => null)
    if (response.ok) return { ok: true, data }
    const code = (data as { error?: unknown } | null)?.error
    const error = typeof code === 'string' ? code : response.status === 422 ? 'invalid_request' : 'unexpected'
    const retryAfter = Number(response.headers.get('retry-after'))
    return retryAfter > 0 ? { ok: false, status: response.status, error, retryAfter } : { ok: false, status: response.status, error }
  }
}

function refused(error: string): ApiResult {
  return { ok: false, status: 0, error }
}

function validFinger(finger: unknown): finger is number {
  return typeof finger === 'number' && Number.isInteger(finger) && finger >= 1 && finger <= 10
}

const ENROLMENTS = '/api/fingerprint/enrolments'
const VERIFICATIONS = '/api/fingerprint/verifications'
const IDENTIFICATIONS = '/api/fingerprint/identifications'

// Lines of a streamed answer, each without its newline; an event with a whole template's view is several
// megabytes, so a line may arrive in many pieces.
async function readLines(response: Response, line: (text: string) => boolean): Promise<void> {
  if (response.body === null) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true })
      let end = pending.indexOf('\n')
      while (end >= 0) {
        const text = pending.slice(0, end)
        pending = pending.slice(end + 1)
        if (text.trim() !== '' && line(text)) return
        end = pending.indexOf('\n')
      }
      if (done) break
    }
    if (pending.trim() !== '') line(pending)
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
