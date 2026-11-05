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
  // H34: a finger's position, 1 to 10, in place of {finger}.
  deleteFingerprint: ['DELETE', '/api/fingerprint/fingers/{finger}'],
} as const satisfies Record<string, readonly ['GET' | 'POST' | 'DELETE', string]>

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

// Fingerprint enrolment (H33): the server answers with one event after another while the finger is placed
// and lifted; the last is `saved` or `failed`. Images are PNG and arrays are little-endian, both in base64.
export interface Check {
  name: string
  passed: boolean
  detail: string
  score?: number | null
}

export interface Pair {
  probe: number
  reference: number
  score: number | null
  accepted: boolean
}

export interface SealedLayout {
  length: number
  head: string
  tag: string
  magic: number
  version: number
  salt: number
  nonce: number
  ciphertext: number
  tag_bytes: number
}

export interface SavedTemplate {
  id: string
  sample_id: string
  placement: number
  algorithm: string
  version: string
  created_at: string
  keypoints: number
  points: string
  descriptors: string
  template_length: number
  sealed: SealedLayout
}

export interface SavedEnrolment {
  enrolment: { id: string; finger: number; created_at: string; replaced_previous: boolean }
  samples: Array<{ id: string; placement: number; captured_at: string; media_type: string; sealed_length: number; quality: number }>
  templates: SavedTemplate[]
  pairs: Pair[]
  threshold: number
  pending_methods: string[]
  not_kept: number[]
}

export type EnrolmentEvent =
  | { type: 'started'; finger: number; placements: number; quality_minimum: number; threshold: number; most_kept: number }
  | { type: 'place'; placement: number; kept: number }
  | { type: 'rejected'; reason: 'quality'; image: string; checks: Check[]; score: number | null; minimum: number }
  | { type: 'kept'; placement: number; image: string; checks: Check[]; keypoints: number; pairs: Pair[] }
  | { type: 'another_placement'; kept: number }
  | { type: 'lift' }
  | ({ type: 'saved' } & SavedEnrolment)
  | { type: 'failed'; error: string }

export interface MbsBridge {
  call<T = unknown>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>>
  setTheme(theme: Theme): void
  // The link that opened the client since the last call, once; `onLink` tells when one arrives.
  takeLink(): Promise<OpenedLink | null>
  onLink(listener: () => void): () => void
  // A fingerprint enrolment (H33): resolves when it has ended, or at once with the server's refusal; its
  // events reach `onEnrolment` listeners. One at a time; `cancelEnrolment` stops it and the scanner.
  enrolFingerprint(finger: number): Promise<ApiResult<null>>
  cancelEnrolment(): void
  onEnrolment(listener: (event: EnrolmentEvent) => void): () => void
}
