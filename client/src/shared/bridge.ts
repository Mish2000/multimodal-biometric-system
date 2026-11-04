// What the page may ask of the main process (H26): named server routes, the theme, and the links that
// opened the client (H32), nothing else.

export const ROUTES = {
  health: ['GET', '/api/health'],
  register: ['POST', '/api/register'],
  login: ['POST', '/api/login'],
  logout: ['POST', '/api/logout'],
  me: ['GET', '/api/me'],
  changePassword: ['POST', '/api/me/password'],
  changeTheme: ['POST', '/api/me/theme'],
  changeLanguage: ['POST', '/api/me/language'],
  requestReset: ['POST', '/api/password-reset'],
  // The main process adds the token of the link that opened the client to these two (H32).
  checkResetLink: ['POST', '/api/password-reset/check'],
  completeReset: ['POST', '/api/password-reset/complete'],
  accounts: ['GET', '/api/admin/accounts'],
  newAdministrator: ['POST', '/api/admin/administrators'],
  setStatus: ['POST', '/api/admin/accounts/{id}/status'],
  audit: ['GET', '/api/admin/audit'],
} as const satisfies Record<string, readonly ['GET' | 'POST', string]>

export type RouteName = keyof typeof ROUTES

export const THEMES = ['system', 'light', 'dark'] as const
export type Theme = (typeof THEMES)[number]

// English is the default; Hebrew is the other choice (H31).
export const LANGUAGES = ['en', 'he'] as const
export type Language = (typeof LANGUAGES)[number]

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
  language: Language
}

// A link that opened the client (H32), as the page learns of it: what it is for and the language of the
// message it came in. Its token stays in the main process, like the session's.
export interface OpenedLink {
  kind: 'reset-password'
  language: Language | null
}

export interface MbsBridge {
  call<T = unknown>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>>
  setTheme(theme: Theme): void
  // The link that opened the client since the last call, once; `onLink` tells when one arrives.
  takeLink(): Promise<OpenedLink | null>
  onLink(listener: () => void): () => void
}
