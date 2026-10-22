// What the page may ask of the main process (H26): named server routes and the theme, nothing else.

export const ROUTES = {
  health: ['GET', '/api/health'],
  register: ['POST', '/api/register'],
  login: ['POST', '/api/login'],
  logout: ['POST', '/api/logout'],
  me: ['GET', '/api/me'],
  changePassword: ['POST', '/api/me/password'],
  changeTheme: ['POST', '/api/me/theme'],
  accounts: ['GET', '/api/admin/accounts'],
  newAdministrator: ['POST', '/api/admin/administrators'],
  setStatus: ['POST', '/api/admin/accounts/{id}/status'],
  audit: ['GET', '/api/admin/audit'],
} as const satisfies Record<string, readonly ['GET' | 'POST', string]>

export type RouteName = keyof typeof ROUTES

export const THEMES = ['system', 'light', 'dark'] as const
export type Theme = (typeof THEMES)[number]

// An answer of the server as the page sees it; `error` is the server's code, or one of the bridge's own:
// server_unreachable, unknown_route, invalid_request, unexpected.
export type ApiResult<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: string; retryAfter?: number }

export interface Account {
  id: string
  username: string
  email: string
  role: 'user' | 'admin'
  must_change_password: boolean
  theme: Theme
}

export interface MbsBridge {
  call<T = unknown>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>>
  setTheme(theme: Theme): void
}
