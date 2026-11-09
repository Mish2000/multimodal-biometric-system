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
  fingerprintMethods: ['GET', '/api/fingerprint/methods'],
  // H48: the face. The page owns the camera; the server finds faces, checks taken images and enrols them.
  faceMethod: ['GET', '/api/face/method'],
  detectFace: ['POST', '/api/face/detect'],
  checkFace: ['POST', '/api/face/checks'],
  enrolFace: ['POST', '/api/face/enrolments'],
  deleteFace: ['DELETE', '/api/face/enrolment'],
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

export const FINGERPRINT_ALGORITHMS = ['opencv-sift', 'learned-pore', 'pore-sift'] as const
export type FingerprintAlgorithm = (typeof FINGERPRINT_ALGORITHMS)[number]
export interface FingerprintMethod {
  code: FingerprintAlgorithm
  threshold: number
  threshold_provisional: boolean
  threshold_origin: string
  available: boolean
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
  prepared_methods?: Array<{ algorithm: string; templates: number }>
  referee?: string
  method_comparisons?: Array<{ algorithm: string; threshold: number; threshold_provisional: boolean; pairs: Pair[] }>
  not_kept: number[]
}

export type EnrolmentEvent =
  | { type: 'started'; finger: number; placements: number; quality_minimum: number; threshold: number; most_kept: number }
  | { type: 'place'; placement: number; kept: number }
  | { type: 'rejected'; reason: 'quality'; image: string; checks: Check[]; score: number | null; minimum: number }
  | { type: 'kept'; placement: number; image: string; checks: Check[]; keypoints: number; pairs: Pair[] }
  | { type: 'another_placement'; kept: number }
  | { type: 'lift' }
  | { type: 'templates'; algorithm: string; completed: number; total: number }
  | ({ type: 'saved' } & SavedEnrolment)
  | { type: 'failed'; error: string }

// H35, H43: the captured image and the caller's highest-scoring stored image can be shown with match coordinates.
export interface MatchViewData {
  placement: number
  reference_image: string
  count: number
  pairs: string // little-endian float32: probe x/y, reference x/y, one row per counted inlier
}

export interface VerificationResult {
  attempt_id: string
  at: string
  finger: number
  algorithm: string
  score: number
  threshold: number
  threshold_origin: string
  threshold_provisional?: boolean
  accepted: boolean
  duration_ms: number
  comparisons: Array<{ placement: number; score: number; accepted: boolean; computed: boolean }>
  match_view?: MatchViewData
}

export type VerificationEvent =
  | { type: 'started'; finger: number; threshold: number; quality_minimum: number; references: number }
  | { type: 'preparing_templates'; completed: number; total: number }
  | { type: 'place'; capture: number; maximum: number }
  | { type: 'checking' }
  | { type: 'rejected'; image: string; checks: Check[]; score: number | null; minimum: number }
  | { type: 'lift' }
  | { type: 'captured'; image: string; checks: Check[] }
  | { type: 'comparing'; completed: number; total: number }
  | { type: 'saving' }
  | ({ type: 'verified' } & VerificationResult)
  | { type: 'failed'; error: string }

// H41: other candidates have only a rank for this attempt, never a stable identifier or a sample.
export interface IdentificationResult {
  attempt_id: string
  at: string
  algorithm: FingerprintAlgorithm
  score: number
  threshold: number
  threshold_origin: string
  threshold_provisional: boolean
  accepted: boolean
  duration_ms: number
  gallery_size: number
  enrolments: number
  tied_leaders: number
  candidates: Array<{ rank: number; own: boolean; finger: number | null; score: number; accepted: boolean }>
  // H45: only for the caller's own highest-ranked print among the shown candidates.
  match_view?: MatchViewData & { rank: number; finger: number }
}

export type IdentificationEvent =
  | { type: 'started'; algorithm: FingerprintAlgorithm; threshold: number; quality_minimum: number; gallery_size: number; enrolments: number }
  | { type: 'preparing_templates'; algorithm: FingerprintAlgorithm; completed: number; total: number }
  | { type: 'place'; capture: number; maximum: number }
  | { type: 'checking' | 'lift' | 'extracting' | 'saving' }
  | { type: 'rejected'; image: string; checks: Check[]; score: number | null; minimum: number }
  | { type: 'captured'; image: string; checks: Check[] }
  | { type: 'searching'; completed: number; total: number }
  | ({ type: 'identified' } & IdentificationResult)
  | { type: 'failed'; error: string }

// H48: a face as YuNet reports it, in the pixels of the image it was found in: its box (x, y, width, height),
// five landmarks (the eyes, the nose tip and the mouth's corners) and the detector's score.
export interface FaceBox {
  box: [number, number, number, number]
  landmarks: Array<[number, number]>
  score: number
}

export interface FaceDetection {
  width: number
  height: number
  faces: FaceBox[]
}

// The checks of a taken image: one_face (count), detector_score (score, minimum), inside, face_size (width, minimum).
export interface FaceCheck extends Check {
  count?: number
  minimum?: number
  width?: number
}

export interface FaceCheckResult extends FaceDetection {
  checks: FaceCheck[]
  passed: boolean
  aligned: string | null // SFace's 112 x 112 input, PNG in base64, when the image passed
}

export interface FaceMethod {
  code: 'sface'
  threshold: number
  threshold_provisional: boolean
  threshold_origin: string
  available: boolean
  images: number
  most_kept: number
  score_minimum: number
  width_minimum: number
  embedding_length: number
}

// Images are numbered in the order they were taken, from 1; probe is the later one.
export interface FacePair {
  probe: number
  reference: number
  score: number
  accepted: boolean
}

export interface FaceSaved {
  status: 'saved'
  enrolment: { id: string; created_at: string; replaced_previous: boolean }
  samples: Array<{ id: string; placement: number; captured_at: string; width: number; height: number; sealed_length: number; aligned: string }>
  templates: Array<{ id: string; sample_id: string; algorithm: string; version: string; embedding_length: number }>
  pairs: FacePair[]
  threshold: number
  not_kept: number[]
}

export type FaceEnrolmentAnswer =
  | FaceSaved
  | { status: 'another'; pairs: FacePair[]; threshold: number; kept: number }
  | { status: 'failed'; error: string; pairs: FacePair[]; threshold: number; kept: number }

// H48: whether the laptop's own screen is in use. With the lid closed and external monitors on, Windows turns
// it off, and the built-in camera sees only the inside of the lid.
export interface DisplayState {
  internalDisplay: boolean
}

export interface MbsBridge {
  call<T = unknown>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>>
  // H48: the built-in screen's state now, and whenever it changes (the lid opened or closed).
  displays(): Promise<DisplayState>
  onDisplays(listener: (state: DisplayState) => void): () => void
  setTheme(theme: Theme): void
  // The link that opened the client since the last call, once; `onLink` tells when one arrives.
  takeLink(): Promise<OpenedLink | null>
  onLink(listener: () => void): () => void
  // A fingerprint enrolment (H33): resolves when it has ended, or at once with the server's refusal; its
  // events reach `onEnrolment` listeners. One at a time; `cancelEnrolment` stops it and the scanner.
  enrolFingerprint(finger: number): Promise<ApiResult<null>>
  cancelEnrolment(): void
  onEnrolment(listener: (event: EnrolmentEvent) => void): () => void
  // Each verification has a page-generated id, so a cancelled run cannot update a later screen (H35).
  verifyFingerprint(finger: number, runId: string, algorithm?: FingerprintAlgorithm): Promise<ApiResult<null>>
  cancelVerification(runId: string): void
  onVerification(runId: string, listener: (event: VerificationEvent) => void): () => void
  identifyFingerprint(runId: string, algorithm?: FingerprintAlgorithm): Promise<ApiResult<null>>
  cancelIdentification(runId: string): void
  onIdentification(runId: string, listener: (event: IdentificationEvent) => void): () => void
}
