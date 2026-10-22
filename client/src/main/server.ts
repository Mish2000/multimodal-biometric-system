// Requests to the local server on behalf of the page (H11, H26). The session token is kept here and is
// never handed to the page, so a script running in the page cannot read or send it elsewhere.
import { ROUTES, type ApiResult, type RouteName } from '../shared/bridge'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const TIMEOUT_MS = 15_000

export class ServerClient {
  private token: string | null = null

  constructor(
    private readonly base: string,
    private readonly request: typeof fetch = fetch,
  ) {}

  get signedIn(): boolean {
    return this.token !== null
  }

  async call(route: unknown, body?: unknown, id?: unknown): Promise<ApiResult> {
    if (typeof route !== 'string' || !Object.hasOwn(ROUTES, route)) return refused('unknown_route')
    const [method, template] = ROUTES[route as RouteName]
    let path: string = template
    if (template.includes('{id}')) {
      if (typeof id !== 'string' || !UUID.test(id)) return refused('unknown_route')
      path = template.replace('{id}', id)
    }
    if (route === 'logout') {
      // Signing out ends the session here even when the server is gone or the session already expired.
      const token = this.token
      this.token = null
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
