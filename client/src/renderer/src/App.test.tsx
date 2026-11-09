/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { Account, ApiResult, EnrolmentEvent, Language, MbsBridge, OpenedLink, RouteName, Theme, VerificationEvent, FingerprintAlgorithm, IdentificationEvent } from '../../shared/bridge'
import { App } from './App'
import { SessionProvider } from './session'

interface Stored extends Account {
  password: string
  status: 'active' | 'disabled'
  phone: string
}

const view = ({ password: _password, status: _status, phone: _phone, ...account }: Stored): Account => account

// The server as the page sees it through the bridge, in memory: as much of the API as the screens use. The
// reset link's token stays in the main process, so here a link simply names its account.
class FakeServer implements MbsBridge {
  accounts: Stored[] = []
  current: Stored | null = null
  up = true
  themes: Theme[] = []
  resets: Array<Record<string, string>> = []
  opened: OpenedLink | null = null
  linked: Stored | null = null
  private listeners = new Set<() => void>()
  // Fingerprint enrolment (H33): the events the next enrolment sends, the enrolled fingers, and what was asked.
  enrolment: EnrolmentEvent[] = []
  fingers: number[] = []
  enrolments: number[] = []
  cancelled = 0
  private enrolmentListeners = new Set<(event: EnrolmentEvent) => void>()
  verification: VerificationEvent[] = []
  verifications: Array<{ finger: number; runId: string; algorithm: FingerprintAlgorithm }> = []
  verificationCancels: string[] = []
  poreAvailable = true
  learnedAvailable = true
  private verificationListeners = new Map<string, (event: VerificationEvent) => void>()
  identification: IdentificationEvent[] = []
  identifications: string[] = []
  identificationMethods: FingerprintAlgorithm[] = []
  identificationCancels: string[] = []
  private identificationListeners = new Map<string, (event: IdentificationEvent) => void>()

  identifyFingerprint = async (runId: string, algorithm: FingerprintAlgorithm = 'opencv-sift'): Promise<ApiResult<null>> => {
    this.identifications.push(runId)
    this.identificationMethods.push(algorithm)
    for (const event of this.identification) {
      await Promise.resolve()
      this.emitIdentification(event, runId)
    }
    return { ok: true, data: null }
  }

  emitIdentification(event: IdentificationEvent, runId = this.identifications.at(-1)): void {
    if (runId) this.identificationListeners.get(runId)?.(event)
  }

  cancelIdentification = (runId: string): void => {
    this.identificationCancels.push(runId)
    this.emitIdentification({ type: 'failed', error: 'cancelled' }, runId)
  }

  onIdentification = (runId: string, listener: (event: IdentificationEvent) => void): (() => void) => {
    this.identificationListeners.set(runId, listener)
    return () => { this.identificationListeners.delete(runId) }
  }

  verifyFingerprint = async (finger: number, runId: string, algorithm: FingerprintAlgorithm = 'opencv-sift'): Promise<ApiResult<null>> => {
    this.verifications.push({ finger, runId, algorithm })
    for (const event of this.verification) {
      await Promise.resolve()
      this.emitVerification(event, runId)
    }
    return { ok: true, data: null }
  }

  emitVerification(event: VerificationEvent, runId = this.verifications.at(-1)?.runId): void {
    if (runId) this.verificationListeners.get(runId)?.(event)
  }

  cancelVerification = (runId: string): void => {
    this.verificationCancels.push(runId)
    this.emitVerification({ type: 'failed', error: 'cancelled' }, runId)
  }

  onVerification = (runId: string, listener: (event: VerificationEvent) => void): (() => void) => {
    this.verificationListeners.set(runId, listener)
    return () => { this.verificationListeners.delete(runId) }
  }

  add(username: string, role: Account['role'], extra: Partial<Stored> = {}): Stored {
    const account: Stored = {
      id: `00000000-0000-4000-8000-${String(this.accounts.length + 1).padStart(12, '0')}`,
      username,
      email: `${username}@example.com`,
      role,
      must_change_password: false,
      theme: 'system',
      language: 'en',
      password: `${username} password 1`,
      status: 'active',
      phone: '',
      ...extra,
    }
    this.accounts.push(account)
    return account
  }

  // A reset link that opened the client, for `account` (none: an unknown or expired link).
  openLink(account: Stored | null, language: Language | null): void {
    this.linked = account
    this.opened = { kind: 'reset-password', language }
    for (const listener of this.listeners) listener()
  }

  setTheme = (theme: Theme): void => {
    this.themes.push(theme)
  }

  takeLink = async (): Promise<OpenedLink | null> => {
    const opened = this.opened
    this.opened = null
    return opened
  }

  onLink = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  enrolFingerprint = async (finger: number): Promise<ApiResult<null>> => {
    this.enrolments.push(finger)
    for (const event of this.enrolment) {
      await Promise.resolve()
      this.emitEnrolment(event)
      if (event.type === 'saved' && !this.fingers.includes(finger)) this.fingers.push(finger)
    }
    return { ok: true, data: null }
  }

  emitEnrolment(event: EnrolmentEvent): void {
    for (const listener of this.enrolmentListeners) listener(event)
  }

  cancelEnrolment = (): void => {
    this.cancelled++
  }

  onEnrolment = (listener: (event: EnrolmentEvent) => void): (() => void) => {
    this.enrolmentListeners.add(listener)
    return () => {
      this.enrolmentListeners.delete(listener)
    }
  }

  call = async <T,>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>> =>
    this.answer(route, (body ?? {}) as Record<string, string>, id) as ApiResult<T>

  private answer(route: RouteName, body: Record<string, string>, id?: string): ApiResult {
    const ok = (data: unknown = null): ApiResult => ({ ok: true, data })
    const no = (status: number, error: string): ApiResult => ({ ok: false, status, error })
    if (!this.up) return no(0, 'server_unreachable')
    switch (route) {
      case 'fingerprintMethods':
        return ok({ methods: [
          { code: 'opencv-sift', threshold: 57, threshold_provisional: false, threshold_origin: 'SD302', available: true },
          { code: 'learned-pore', threshold: 21, threshold_provisional: true, threshold_origin: 'H10', available: this.learnedAvailable },
          { code: 'pore-sift', threshold: 37, threshold_provisional: true, threshold_origin: 'H10', available: this.poreAvailable },
        ] })
      case 'deleteFingerprint': {
        const finger = Number(id)
        if (!this.fingers.includes(finger)) return no(404, 'not_enrolled')
        this.fingers = this.fingers.filter((f) => f !== finger)
        return ok()
      }
      case 'health':
        return ok({ status: 'ok' })
      case 'register': {
        if (this.accounts.some((a) => a.username === body.username)) return no(409, 'username_taken')
        const created = this.add(body.username ?? '', 'user', {
          email: body.email ?? '',
          password: body.password ?? '',
          phone: body.phone ?? '',
          language: body.language as Language,
        })
        return ok({ account: view(created) })
      }
      case 'login': {
        const found = this.accounts.find((a) => (a.username === body.login || a.email === body.login) && a.password === body.password)
        if (found === undefined) return no(401, 'wrong_credentials')
        if (found.status === 'disabled') return no(403, 'account_disabled')
        if (body.language) found.language = body.language as Language
        this.current = found
        return ok({ account: view(found) })
      }
      case 'logout':
        this.current = null
        return ok()
      case 'requestReset':
        this.resets.push(body)
        return ok()
      case 'checkResetLink':
        return this.linked ? ok() : no(400, 'invalid_reset_link')
      case 'completeReset':
        if (this.linked === null) return no(400, 'invalid_reset_link')
        this.linked.password = body.password ?? ''
        this.linked = null
        return ok()
    }
    const me = this.current
    if (me === null) return no(401, 'not_signed_in')
    switch (route) {
      case 'me': {
        const fingerprint = { enrolled: this.fingers.length > 0, fingers: [...this.fingers].sort((a, b) => a - b) }
        const modalities = { fingerprint, face: { enrolled: false }, voice: { enrolled: false } }
        return ok({ account: view(me), modalities: me.role === 'user' ? modalities : null })
      }
      case 'changePassword':
        if (body.current !== me.password) return no(403, 'wrong_password')
        me.password = body.new ?? ''
        me.must_change_password = false
        return ok()
      case 'changeTheme':
        me.theme = body.theme as Theme
        return ok()
      case 'changeLanguage':
        me.language = body.language as Language
        return ok()
      case 'accounts':
        return ok({
          accounts: this.accounts.map(({ id, username, email, role, status }) => ({
            id,
            username,
            email,
            role,
            status,
            created_at: '2026-10-22T09:30:00+00:00',
          })),
        })
      case 'audit':
        return ok({ entries: [{ at: '2026-10-22T09:00:00+00:00', administrator: 'admin', action: 'first_administrator', target: 'admin' }] })
      case 'setStatus': {
        if (body.password !== me.password) return no(403, 'wrong_password')
        const target = this.accounts.find((a) => a.id === id)
        if (target === undefined) return no(404, 'no_such_account')
        target.status = body.status as Stored['status']
        return ok()
      }
      case 'newAdministrator': {
        if (body.password !== me.password) return no(403, 'wrong_password')
        const created = this.add(body.username ?? '', 'admin', {
          email: body.email ?? '',
          password: 'one-time-Kq7xW2',
          must_change_password: true,
        })
        return ok({ account: view(created), one_time_password: created.password })
      }
    }
    return no(404, 'unknown_route')
  }
}

let server: FakeServer

beforeEach(() => {
  server = new FakeServer()
  window.mbs = server
})

afterEach(cleanup)

function open(path: string, strict = false) {
  const page = (
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>
  )
  render(strict ? <StrictMode>{page}</StrictMode> : page)
}

function type(label: string, value: string, scope: HTMLElement = document.body) {
  fireEvent.change(within(scope).getByLabelText(label), { target: { value } })
}

async function signIn(login: string, password: string, texts = { button: 'Sign in', login: 'Username or email', password: 'Password' }) {
  const button = await screen.findByRole('button', { name: texts.button })
  type(texts.login, login)
  type(texts.password, password)
  fireEvent.click(button)
}

describe('the navigation', () => {
  it('signs a user in to the home screen and out again', async () => {
    server.add('dana', 'user', { theme: 'light' })
    open('/')
    await signIn('dana', 'dana password 1')
    expect(await screen.findByRole('heading', { name: 'Hello, dana' })).toBeTruthy()
    expect(await screen.findAllByText('Not enrolled yet')).toHaveLength(3)
    for (const name of ['Fingerprint', 'Face', 'Voice']) expect(screen.getByRole('heading', { name })).toBeTruthy()
    await waitFor(() => expect(server.themes).toEqual(['system', 'light']))
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeTruthy()
    expect(server.current).toBeNull()
    await waitFor(() => expect(server.themes.at(-1)).toBe('system'))
  })

  it('words wrong credentials and a disabled account', async () => {
    server.add('dana', 'user', { status: 'disabled' })
    open('/sign-in')
    await signIn('dana', 'not her password')
    expect(await screen.findByText('The username or password is wrong.')).toBeTruthy()
    await signIn('dana', 'dana password 1')
    expect(await screen.findByText('This account is disabled. You can contact the system administrator.')).toBeTruthy()
  })

  it('says when the server is down, and checks again', async () => {
    server.up = false
    open('/sign-in')
    expect(await screen.findByText(/The server is not running/)).toBeTruthy()
    server.up = true
    fireEvent.click(screen.getByRole('button', { name: 'check again' }))
    await waitFor(() => expect(screen.queryByText(/The server is not running/)).toBeNull())
  })

  it('signs a new account in after registration, with its mobile phone (H29)', async () => {
    open('/register')
    await screen.findByRole('heading', { name: 'New account' })
    type('Username', 'noa')
    type('Email', 'noa@example.com')
    type('Mobile phone', '050-123-4567')
    type('Password', 'A long password 1')
    type('National ID', '000000018')
    fireEvent.click(screen.getByRole('button', { name: 'Create the account' }))
    expect(await screen.findByRole('heading', { name: 'Hello, noa' })).toBeTruthy()
    expect(server.accounts[0]).toMatchObject({ phone: '050-123-4567', language: 'en' })
  })

  it('keeps an administrator with a one-time password on the password screen until it is replaced', async () => {
    server.add('admin', 'admin', { must_change_password: true, password: 'one-time-1' })
    server.add('dana', 'user')
    open('/admin')
    await signIn('admin', 'one-time-1')
    expect(await screen.findByRole('heading', { name: 'Choose a new password' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Administration' })).toBeNull()
    type('One-time password', 'one-time-1')
    type('New password', 'A new password 1')
    type('New password again', 'Another password 1')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('The two new passwords are not the same.')).toBeTruthy()
    type('New password again', 'A new password 1')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('heading', { name: 'Administration', level: 1 })).toBeTruthy()
    expect(await screen.findByRole('row', { name: /dana/ })).toBeTruthy()
  })

  it('sends a user who opens the administration area home, with the session the main process kept', async () => {
    server.current = server.add('dana', 'user')
    open('/admin')
    expect(await screen.findByRole('heading', { name: 'Hello, dana' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Administration' })).toBeNull()
  })

  it('returns to sign-in with a notice when the server has ended the session', async () => {
    server.current = server.add('dana', 'user')
    open('/settings')
    const dark = await screen.findByLabelText('Dark')
    server.current = null
    fireEvent.click(dark)
    expect(await screen.findByText('Your sign-in has ended. Please sign in again.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()
  })
})

describe('the language (H31)', () => {
  const hebrew = { button: 'כניסה', login: 'שם משתמש או אימייל', password: 'סיסמה' }

  it('is English by default; Hebrew chosen at sign-in turns the screens right to left and enters the account', async () => {
    server.add('dana', 'user')
    open('/sign-in')
    await screen.findByRole('heading', { name: 'Identification System' })
    expect(document.documentElement.dir).toBe('ltr')
    fireEvent.click(screen.getByRole('button', { name: 'עברית' }))
    expect(await screen.findByRole('heading', { name: 'מערכת הזיהוי' })).toBeTruthy()
    expect(document.documentElement.dir).toBe('rtl')
    expect(document.documentElement.lang).toBe('he')
    await signIn('dana', 'dana password 1', hebrew)
    expect(await screen.findByRole('heading', { name: 'שלום, dana' })).toBeTruthy()
    expect(server.accounts[0]?.language).toBe('he')
  })

  it("keeps the account's own language when none was chosen at sign-in, and keeps it after sign-out", async () => {
    server.add('dana', 'user', { language: 'he' })
    open('/sign-in')
    await signIn('dana', 'dana password 1')
    expect(await screen.findByRole('heading', { name: 'שלום, dana' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'יציאה' }))
    expect(await screen.findByRole('button', { name: 'כניסה' })).toBeTruthy()
    expect(server.accounts[0]?.language).toBe('he')
  })

  it('registers the language of the registration screen', async () => {
    open('/register')
    fireEvent.click(await screen.findByRole('button', { name: 'עברית' }))
    await screen.findByRole('heading', { name: 'חשבון חדש' })
    type('שם משתמש', 'noa')
    type('אימייל', 'noa@example.com')
    type('טלפון נייד', '050-123-4567')
    type('סיסמה', 'A long password 1')
    type('מספר זהות', '000000018')
    fireEvent.click(screen.getByRole('button', { name: 'יצירת החשבון' }))
    expect(await screen.findByRole('heading', { name: 'שלום, noa' })).toBeTruthy()
    expect(server.accounts[0]?.language).toBe('he')
  })

  it('is changed in the settings and saved in the account', async () => {
    const dana = server.add('dana', 'user')
    server.current = dana
    open('/settings')
    fireEvent.click(await screen.findByLabelText('עברית'))
    expect(await screen.findByRole('heading', { name: 'הגדרות', level: 1 })).toBeTruthy()
    expect(dana.language).toBe('he')
    fireEvent.click(screen.getByLabelText('English'))
    expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeTruthy()
    expect(dana.language).toBe('en')
  })
})

describe('passwords (H30)', () => {
  it('show their strength while they are typed: invalid, weak, medium, strong', async () => {
    open('/register')
    await screen.findByRole('heading', { name: 'New account' })
    expect(screen.queryByText(/Password strength/)).toBeNull()
    for (const [password, level] of [
      ['abc', 'Invalid'],
      ['ABCDEFG1', 'Weak'],
      ['Abcdefg1', 'Medium'],
      ['Abcdefg1!', 'Strong'],
    ] as const) {
      type('Password', password)
      expect(screen.getByRole('status').textContent).toBe(`Password strength: ${level}`)
    }
  })

  it('can be shown and hidden with the eye', async () => {
    open('/sign-in')
    const input = (await screen.findByLabelText('Password')) as HTMLInputElement
    expect(input.type).toBe('password')
    fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(input.type).toBe('text')
    fireEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(input.type).toBe('password')
  })
})

describe('password recovery (H32)', () => {
  it('sends a link by SMS or by email, and gives the same answer either way', async () => {
    open('/sign-in')
    fireEvent.click(await screen.findByRole('link', { name: 'Forgot your password?' }))
    expect(await screen.findByRole('heading', { name: 'Reset your password' })).toBeTruthy()
    type('Mobile phone', '050-123-4567')
    fireEvent.click(screen.getByRole('button', { name: 'Send the link' }))
    expect(await screen.findByText(/If this number belongs to an account, an SMS with a link is on its way/)).toBeTruthy()
    fireEvent.click(screen.getByLabelText('By email'))
    type('Email', 'dana@example.com')
    fireEvent.click(screen.getByRole('button', { name: 'Send the link' }))
    expect(await screen.findByText(/If this address belongs to an account, an email with a link is on its way/)).toBeTruthy()
    expect(server.resets).toEqual([
      { channel: 'sms', destination: '050-123-4567', language: 'en' },
      { channel: 'email', destination: 'dana@example.com', language: 'en' },
    ])
  })

  it('opens the new-password screen from a link, in its language, and the link works once', async () => {
    const dana = server.add('dana', 'user')
    server.openLink(dana, 'he')
    open('/sign-in')
    expect(await screen.findByRole('heading', { name: 'בחירת סיסמה חדשה' })).toBeTruthy()
    await screen.findByLabelText('סיסמה חדשה') // the link check finishes after the heading appears
    type('סיסמה חדשה', 'Better one 2027!')
    expect(screen.getByRole('status').textContent).toBe('חוזק הסיסמה: חזקה')
    type('הסיסמה החדשה שוב', 'Better one 2027!')
    fireEvent.click(screen.getByRole('button', { name: 'שמירת הסיסמה החדשה' }))
    expect(await screen.findByText(/הסיסמה הוחלפה, וכל הכניסות לחשבון נותקו/)).toBeTruthy()
    expect(dana.password).toBe('Better one 2027!')
    fireEvent.click(screen.getByRole('link', { name: 'לכניסה' }))
    await signIn('dana', 'Better one 2027!', { button: 'כניסה', login: 'שם משתמש או אימייל', password: 'סיסמה' })
    // A link's language only shows the screens in it: the account keeps its own, English.
    expect(await screen.findByRole('heading', { name: 'Hello, dana' })).toBeTruthy()
    expect(dana.language).toBe('en')
  })

  it('says when a link no longer works, and offers a new one', async () => {
    open('/sign-in')
    await screen.findByRole('button', { name: 'Sign in' })
    act(() => server.openLink(null, null)) // a link that arrives while the client runs
    expect(await screen.findByText('This link no longer works. A link works once, for 30 minutes.')).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Ask for a new link' }))
    expect(await screen.findByRole('heading', { name: 'Reset your password' })).toBeTruthy()
  })
})

describe('the settings', () => {
  it("save the account's theme and apply it to the window", async () => {
    const dana = server.add('dana', 'user')
    server.current = dana
    open('/settings')
    fireEvent.click(await screen.findByLabelText('Dark'))
    await waitFor(() => expect(server.themes.at(-1)).toBe('dark'))
    expect(dana.theme).toBe('dark')
    expect((screen.getByLabelText('Dark') as HTMLInputElement).checked).toBe(true)
  })

  it('change the password in the security area, only with the current one (H28)', async () => {
    const dana = server.add('dana', 'user')
    server.current = dana
    open('/settings')
    expect(await screen.findByRole('heading', { name: 'Security' })).toBeTruthy()
    type('Current password', 'not her password')
    type('New password', 'A new password 1')
    expect(screen.getByRole('status').textContent).toBe('Password strength: Strong')
    type('New password again', 'A new password 1')
    fireEvent.click(screen.getByRole('button', { name: 'Change the password' }))
    expect(await screen.findByText('The password is wrong.')).toBeTruthy()
    expect(dana.password).toBe('dana password 1')
    type('Current password', 'dana password 1')
    fireEvent.click(screen.getByRole('button', { name: 'Change the password' }))
    expect(await screen.findByText('The password was changed. Your other sign-ins were signed out.')).toBeTruthy()
    expect(dana.password).toBe('A new password 1')
    expect((screen.getByLabelText('Current password') as HTMLInputElement).value).toBe('')
  })

  it('have no password screen of their own: the bar has no link, and its old address leads home', async () => {
    server.current = server.add('dana', 'user')
    open('/password')
    expect(await screen.findByRole('heading', { name: 'Hello, dana' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Change the password' })).toBeNull()
    const bar = screen.getByRole('navigation')
    expect(within(bar).getAllByRole('link').map((link) => link.textContent)).toEqual(['Home', 'Settings'])
  })
})

describe('the administration area', () => {
  it('disables an account only after the administrator gives the password again', async () => {
    server.current = server.add('admin', 'admin')
    const dana = server.add('dana', 'user')
    open('/admin')
    const row = await screen.findByRole('row', { name: /dana/ })
    expect(within(screen.getByRole('row', { name: /admin@example\.com/ })).getByText('Your account')).toBeTruthy()
    fireEvent.click(within(row).getByRole('button', { name: 'Disable…' }))
    type('Your password, to confirm', 'not the password', row)
    fireEvent.click(within(row).getByRole('button', { name: 'Disable' }))
    expect(await within(row).findByText('The password is wrong.')).toBeTruthy()
    expect(dana.status).toBe('active')
    type('Your password, to confirm', 'admin password 1', row)
    fireEvent.click(within(row).getByRole('button', { name: 'Disable' }))
    expect(await within(row).findByText('Disabled')).toBeTruthy()
    expect(dana.status).toBe('disabled')
  })

  it("shows a new administrator's one-time password once", async () => {
    server.current = server.add('admin', 'admin')
    open('/admin')
    const create = await screen.findByRole('button', { name: 'Create' })
    const form = create.closest('form') as HTMLFormElement
    type('Username', 'rotem', form)
    type('Email', 'rotem@example.com', form)
    type('Your password, to confirm', 'admin password 1', form)
    fireEvent.click(create)
    expect((await screen.findByRole('status')).textContent).toContain('one-time-Kq7xW2')
    expect(await screen.findByRole('row', { name: /rotem/ })).toBeTruthy()
  })
})

// Fingerprint enrolment (H33). The images are placeholders and the arrays are tiny; the canvases do not draw
// in jsdom, so these tests follow the texts and the flow.
const CHECKS = [
  { name: 'size', passed: true, detail: '1000x1000 (expected 1000x1000)' },
  { name: 'resolution', passed: true, detail: '1000x1000 ppi (expected 1000)' },
  { name: 'ridge texture', passed: true, detail: 'centre spread 61.2 gray levels (at least 20)' },
  { name: 'fine detail', passed: true, detail: 'a 500 ppi round trip keeps 0.180 (at most 0.40)' },
  { name: 'quality', passed: true, detail: 'NFIQ 2 score 64 (at least 35)', score: 64 },
]

function b64(bytes: Uint8Array): string {
  let text = ''
  for (const b of bytes) text += String.fromCharCode(b)
  return btoa(text)
}

function template(placement: number) {
  return {
    id: `10000000-0000-4000-8000-00000000000${placement}`,
    sample_id: `20000000-0000-4000-8000-00000000000${placement}`,
    placement,
    algorithm: 'opencv-sift',
    version: '606c8d33a7a27570b5bb55cca8248259b9b6ba8a',
    created_at: '2026-11-06T10:00:00+00:00',
    keypoints: 3,
    points: b64(new Uint8Array(new Float32Array([100, 200, 400, 500, 800, 900]).buffer)),
    descriptors: b64(new Uint8Array(3 * 128).map((_, i) => i % 256)),
    template_length: 4_300_000,
    sealed: { length: 4_300_066, head: b64(new Uint8Array(98)), tag: b64(new Uint8Array(16)), magic: 4, version: 2, salt: 32, nonce: 12, ciphertext: 4_300_000, tag_bytes: 16 },
  }
}

function kept(placement: number, pairs: Array<[number, number, number]>): EnrolmentEvent {
  return {
    type: 'kept', placement, image: 'AAAA', checks: CHECKS, keypoints: 3,
    pairs: pairs.map(([probe, reference, score]) => ({ probe, reference, score, accepted: score > 57 })),
  }
}

const STARTED: EnrolmentEvent = { type: 'started', finger: 7, placements: 3, quality_minimum: 35, threshold: 57, most_kept: 6 }

const SAVED: EnrolmentEvent = {
  type: 'saved',
  enrolment: { id: '30000000-0000-4000-8000-000000000001', finger: 7, created_at: '2026-11-06T10:00:00+00:00', replaced_previous: false },
  samples: [1, 2, 3].map((placement) => ({ id: `20000000-0000-4000-8000-00000000000${placement}`, placement, captured_at: '2026-11-06T10:00:00+00:00', media_type: 'image/png', sealed_length: 330_066, quality: 64 })),
  templates: [template(1), template(2), template(3)],
  pairs: [
    { probe: 2, reference: 1, score: 601, accepted: true },
    { probe: 3, reference: 1, score: 384, accepted: true },
    { probe: 3, reference: 2, score: 562, accepted: true },
  ],
  threshold: 57,
  pending_methods: ['pore-sift', 'learned-pore'],
  not_kept: [],
}

async function openFingerprint() {
  server.add('dana', 'user')
  open('/sign-in')
  await signIn('dana', 'dana password 1')
  fireEvent.click(await screen.findByRole('link', { name: 'Open' }))
  await screen.findByRole('heading', { name: 'Fingerprint' })
}

describe('fingerprint enrolment (H33)', () => {
  it('enrols the chosen finger with live guidance, then shows how its template is stored', async () => {
    server.enrolment = [
      STARTED,
      { type: 'place', placement: 1, kept: 0 }, kept(1, []), { type: 'lift' },
      { type: 'place', placement: 2, kept: 1 }, kept(2, [[2, 1, 601]]), { type: 'lift' },
      { type: 'place', placement: 3, kept: 2 }, kept(3, [[3, 1, 384], [3, 2, 562]]),
      SAVED,
    ]
    await openFingerprint()
    const left = screen.getByRole('group', { name: 'Left hand' })
    fireEvent.click(within(left).getByRole('button', { name: 'Index' }))
    expect(screen.getByText('left index')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Enrol this finger' }))
    await screen.findByRole('heading', { name: 'How your fingerprint is stored' })
    expect(server.enrolments).toEqual([7])
    expect(screen.getByText(/Shown once, now/)).toBeTruthy()
    expect(screen.getByText('Quality (NFIQ 2)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText(/OpenCV SIFT finds 3 distinctive points/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Move the pointer over the print to choose a point.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText(/a table of 3 rows \(points\) by 128 columns/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('opencv-sift')).toBeTruthy()
    expect(screen.getByText('MBS1 header: 4 bytes')).toBeTruthy()
    expect(screen.getByText('tag: 16 bytes')).toBeTruthy()
    expect(screen.getAllByText('Pore SIFT')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('601')).toBeTruthy()
    expect(screen.getAllByText('above 57: match')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    await screen.findByText('enrolled')
    expect(screen.getByRole('button', { name: 'Enrol this finger again' })).toBeTruthy()
    expect(screen.getByText('A new enrolment replaces the earlier one; the earlier one stays stored.')).toBeTruthy()
  })

  it('says why a capture was not kept, words a failure, and tries again', async () => {
    server.enrolment = [
      STARTED,
      { type: 'place', placement: 1, kept: 0 },
      { type: 'rejected', reason: 'quality', image: 'AAAA', checks: [...CHECKS.slice(0, 4), { name: 'quality', passed: false, detail: 'NFIQ 2 score 20 (at least 35)', score: 20 }], score: 20, minimum: 35 },
      { type: 'lift' },
    ]
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Right hand' })).getByRole('button', { name: 'Thumb' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enrol this finger' }))
    expect(await screen.findByText(/The quality is 20, below the minimum of 35/)).toBeTruthy()
    expect(screen.getByText('Lift the finger off the glass.')).toBeTruthy()
    act(() => server.emitEnrolment({ type: 'failed', error: 'no_finger' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'No finger was placed within a minute.')
    server.enrolment = [STARTED, { type: 'place', placement: 1, kept: 0 }]
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Place the finger on the scanner and hold it still until it is kept.')).toBeTruthy()
    expect(server.enrolments).toEqual([1, 1])
  })

  it('stops the scanner when the enrolment is cancelled or left', async () => {
    server.enrolment = [STARTED, { type: 'place', placement: 1, kept: 0 }]
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: 'Ring' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enrol this finger' }))
    await screen.findByText('Place the finger on the scanner and hold it still until it is kept.')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(server.cancelled).toBe(1)
    act(() => server.emitEnrolment({ type: 'failed', error: 'cancelled' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'The enrolment was cancelled.')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByText('Place the finger on the scanner and hold it still until it is kept.')
    fireEvent.click(screen.getByRole('link', { name: 'Home' }))
    await screen.findByRole('heading', { name: /Hello/ })
    expect(server.cancelled).toBe(2)
  })

  it('shows the screens in Hebrew too', async () => {
    server.add('noa', 'user', { language: 'he' })
    open('/sign-in')
    await signIn('noa', 'noa password 1')
    fireEvent.click(await screen.findByRole('link', { name: 'פתיחה' }))
    expect(await screen.findByRole('heading', { name: 'טביעת אצבע' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'יד שמאל' })).toBeTruthy()
  })
})

const VERIFIED: VerificationEvent = {
  type: 'verified', attempt_id: '00000000-0000-4000-8000-000000000001', at: '2026-11-06T10:00:00Z',
  finger: 7, algorithm: 'opencv-sift', score: 88, threshold: 57, threshold_origin: 'SD302 plain vs plain, FAR 0.1 % (RxJ)',
  accepted: true, duration_ms: 430,
  comparisons: [
    { placement: 1, score: 40, accepted: false, computed: true },
    { placement: 2, score: 57, accepted: false, computed: true },
    { placement: 4, score: 88, accepted: true, computed: true },
  ],
}
const VERIFY_STARTED: VerificationEvent = { type: 'started', finger: 7, threshold: 57, quality_minimum: 35, references: 3 }

async function startVerification() {
  await openFingerprint()
  fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
  if (server.fingers.includes(7)) fireEvent.click(await screen.findByRole('button', { name: 'Start verification' }))
}

describe('fingerprint verification (H35)', () => {
  it('chooses Pore SIFT, guides preparation and shows its saved provisional result (H38)', async () => {
    server.fingers = [7]
    server.verification = [VERIFY_STARTED, { type: 'preparing_templates', completed: 1, total: 3 }]
    await openFingerprint()
    expect(screen.queryByRole('radio')).toBeNull()
    fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
    expect(screen.getByRole('radio', { name: 'OpenCV SIFT' })).toHaveProperty('checked', true)
    fireEvent.click(screen.getByRole('radio', { name: 'Pore SIFT' }))
    expect(server.verifications).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Start verification' }))
    expect(await screen.findByText('Creating Pore SIFT templates (1 of 3)…')).toBeTruthy()
    expect(server.verifications[0]?.algorithm).toBe('pore-sift')
    act(() => server.emitVerification({ ...VERIFIED, algorithm: 'pore-sift', score: 45, threshold: 37,
      threshold_provisional: true,
      comparisons: VERIFIED.comparisons.map((c) => ({ ...c, score: 45, accepted: true })) }))
    expect(await screen.findByRole('heading', { name: 'Fingerprint matches' })).toBeTruthy()
    expect(screen.getByRole('meter', { name: 'Matching pores' })).toHaveProperty('value', 45)
    expect(screen.getByText(/This threshold is provisional on the HiScan PRO/)).toBeTruthy()
    expect(screen.getByText('Match above 37')).toBeTruthy()
  })

  it('cancels preparation and retries with the selected method (H38)', async () => {
    server.fingers = [7]
    server.verification = [{ type: 'preparing_templates', completed: 0, total: 3 }]
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Pore SIFT' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start verification' }))
    await screen.findByText('Creating Pore SIFT templates (0 of 3)…')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await screen.findByText('Verification cancelled.')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(server.verifications).toHaveLength(2))
    expect(server.verifications.map((run) => run.algorithm)).toEqual(['pore-sift', 'pore-sift'])
  })

  it('keeps an unavailable method disabled and OpenCV SIFT usable (H38)', async () => {
    server.poreAvailable = false
    server.fingers = [7]
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
    expect(screen.getByRole('radio', { name: 'Pore SIFT' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('radio', { name: 'OpenCV SIFT' })).toHaveProperty('disabled', false)
    expect(screen.getByText('This method is unavailable on this computer. Check the server configuration.')).toBeTruthy()
  })

  it('starts just one verification in development StrictMode', async () => {
    server.current = server.add('dana', 'user')
    server.fingers = [7]
    server.verification = [VERIFY_STARTED, { type: 'place', capture: 1, maximum: 12 }]
    open('/fingerprint', true)
    fireEvent.click(within(await screen.findByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Start verification' }))
    await screen.findByText('Place the selected finger on the scanner and hold it still.')
    expect(server.verifications).toHaveLength(1)
    expect(server.verificationCancels).toEqual([])
  })

  it('starts just one enrolment in development StrictMode', async () => {
    server.current = server.add('dana', 'user')
    server.enrolment = [STARTED, { type: 'place', placement: 1, kept: 0 }]
    open('/fingerprint', true)
    fireEvent.click(within(await screen.findByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Enrol this finger' }))
    await screen.findByText('Place the finger on the scanner and hold it still until it is kept.')
    expect(server.enrolments).toEqual([7])
    expect(server.cancelled).toBe(0)
  })

  it('offers enrolment or home before starting a scan of an unenrolled finger', async () => {
    await startVerification()
    expect(await screen.findByText(/Enrol this finger before verifying/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Back to home' })).toBeTruthy()
    expect(server.verifications).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Enrol this finger' }))
    await waitFor(() => expect(server.enrolments).toEqual([7]))
  })

  it('shows the saved decision, each original placement score and processing time', async () => {
    server.fingers = [7]
    server.verification = [VERIFY_STARTED, { type: 'captured', image: 'AAAA', checks: CHECKS }, VERIFIED]
    await startVerification()
    expect(await screen.findByRole('heading', { name: 'Fingerprint matches' })).toBeTruthy()
    expect(screen.getByRole('meter')).toHaveProperty('value', 88)
    expect(screen.getByText('Placement 4')).toBeTruthy()
    expect(screen.getAllByText('At or below the threshold')).toHaveLength(2)
    expect(screen.getByText('The result and its encrypted capture were saved.')).toBeTruthy()
    expect(screen.getByText('Processing time 0.43 s')).toBeTruthy()
    server.verification = [VERIFY_STARTED, { type: 'place', capture: 1, maximum: 12 }]
    fireEvent.click(screen.getByRole('button', { name: 'Verify again' }))
    expect(await screen.findByText('Place the selected finger on the scanner and hold it still.')).toBeTruthy()
    expect(screen.queryByText('Fingerprint matches')).toBeNull()
    expect(server.verifications).toHaveLength(2)
    expect(server.verifications[0]?.runId).not.toBe(server.verifications[1]?.runId)
  })

  it('treats a non-match as a completed result with practical retry guidance', async () => {
    server.fingers = [7]
    server.verification = [{ ...VERIFIED, accepted: false, score: 57,
      comparisons: VERIFIED.comparisons.map((p) => ({ ...p, score: 57, accepted: false })) }]
    await startVerification()
    expect(await screen.findByRole('heading', { name: 'Fingerprint does not match' })).toBeTruthy()
    expect(screen.getByText(/Check that you selected the correct finger/)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('guides a quality retry and reports a cancelled run without a result', async () => {
    server.fingers = [7]
    server.verification = [VERIFY_STARTED, { type: 'rejected', image: 'AAAA', checks: CHECKS, score: 20, minimum: 35 }, { type: 'lift' }]
    await startVerification()
    expect(await screen.findByText(/The quality is 20, below the minimum of 35/)).toBeTruthy()
    expect(screen.getByText('Lift the finger off the glass.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('Verification cancelled.')).toBeTruthy()
    expect(screen.queryByText('The result and its encrypted capture were saved.')).toBeNull()
    expect(server.verificationCancels).toEqual([server.verifications[0]?.runId])
  })

  it('cancels on navigation and ignores events from the old run after returning', async () => {
    server.fingers = [7]
    server.verification = [VERIFY_STARTED, { type: 'place', capture: 1, maximum: 12 }]
    await startVerification()
    await screen.findByText('Place the selected finger on the scanner and hold it still.')
    const previous = server.verifications[0]!.runId
    fireEvent.click(screen.getByRole('link', { name: 'Home' }))
    await screen.findByRole('heading', { name: /Hello/ })
    expect(server.verificationCancels).toEqual([previous])
    fireEvent.click(await screen.findByRole('link', { name: 'Open' }))
    fireEvent.click(within(await screen.findByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Start verification' }))
    await screen.findByText('Place the selected finger on the scanner and hold it still.')
    act(() => server.emitVerification(VERIFIED, previous))
    expect(screen.queryByText('Fingerprint matches')).toBeNull()
  })

  it('offers re-enrolment for missing templates and words a lost connection', async () => {
    server.fingers = [7]
    server.verification = [{ type: 'failed', error: 'templates_unavailable' }]
    await startVerification()
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'The three stored templates are incomplete. Enrol this finger again.')
    expect(screen.getByRole('button', { name: 'Enrol this finger again' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Back to the fingers' }))
    server.verification = [{ type: 'failed', error: 'server_unreachable' }]
    fireEvent.click(await screen.findByRole('button', { name: 'Verify this finger (1:1)' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Start verification' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'The connection to the server ended. A completed result may already have been saved. Check the server before starting a new verification.')
  })

  it('shows the verification result in Hebrew with the same scores', async () => {
    server.current = server.add('noa', 'user', { language: 'he' })
    server.fingers = [7]
    server.verification = [VERIFIED]
    open('/fingerprint')
    fireEvent.click(within(await screen.findByRole('group', { name: 'יד שמאל' })).getByRole('button', { name: /מורה/ }))
    fireEvent.click(screen.getByRole('button', { name: 'אימות האצבע הזו (1:1)' }))
    fireEvent.click(await screen.findByRole('button', { name: 'התחלת האימות' }))
    expect(await screen.findByRole('heading', { name: 'נמצאה התאמה לטביעת האצבע' })).toBeTruthy()
    expect(screen.getByText('הנחה 4')).toBeTruthy()
    expect(document.documentElement.dir).toBe('rtl')
  })
})

describe('learned verification and generic enrolment clarity (H39)', () => {
  it.each(['en', 'he'] as const)('selects the learned method before capture and explains preparation and its result in %s', async (language) => {
    server.current = server.add('dana', 'user', { language })
    server.fingers = [7]
    server.verification = [{ type: 'preparing_templates', completed: 1, total: 3 }]
    open('/fingerprint')
    const he = language === 'he'
    const hands = await screen.findByRole('group', { name: he ? 'יד שמאל' : 'Left hand' })
    expect(screen.queryByRole('radio')).toBeNull()
    fireEvent.click(within(hands).getByRole('button', { name: he ? /מורה/ : /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: he ? 'אימות האצבע הזו (1:1)' : 'Verify this finger (1:1)' }))
    fireEvent.click(await screen.findByRole('radio', { name: he ? 'המתאר הנלמד' : 'Learned pore descriptor' }))
    expect(server.verifications).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת האימות' : 'Start verification' }))
    expect(await screen.findByText(he ? 'יוצרים תבניות המתאר הנלמד (1 מתוך 3)…' : 'Creating Learned pore descriptor templates (1 of 3)…')).toBeTruthy()
    expect(server.verifications[0]?.algorithm).toBe('learned-pore')
    act(() => server.emitVerification({ ...VERIFIED, algorithm: 'learned-pore', score: 30, threshold: 21, threshold_provisional: true }))
    expect(await screen.findByRole('heading', { name: he ? 'נמצאה התאמה לטביעת האצבע' : 'Fingerprint matches' })).toBeTruthy()
    expect(screen.getByRole('meter', { name: he ? 'נקבוביות תואמות' : 'Matching pores' })).toHaveProperty('value', 30)
    expect(screen.getByText(he ? 'התאמה מעל 21' : 'Match above 21')).toBeTruthy()
    // H40: changing method keeps the finger and does not start or cancel a completed scan.
    const change = screen.getByRole('button', { name: he ? 'החלפת שיטה' : 'Change method' })
    expect([...change.closest('.actions')!.querySelectorAll('button')].map((button) => button.textContent)).toEqual(
      he ? ['אימות נוסף', 'החלפת שיטה', 'חזרה לבחירת האצבע'] : ['Verify again', 'Change method', 'Back to the fingers'],
    )
    const previous = server.verifications[0]!.runId
    fireEvent.click(change)
    expect(await screen.findByRole('radio', { name: he ? 'המתאר הנלמד' : 'Learned pore descriptor' })).toHaveProperty('checked', true)
    expect(screen.getByText(he ? 'מורה שמאל' : 'left index')).toBeTruthy()
    expect(server.verifications).toHaveLength(1)
    expect(server.verificationCancels).toEqual([])
    fireEvent.click(screen.getByRole('radio', { name: 'Pore SIFT' }))
    server.verification = [{ type: 'place', capture: 1, maximum: 12 }]
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת האימות' : 'Start verification' }))
    await waitFor(() => expect(server.verifications).toHaveLength(2))
    expect(server.verifications[1]).toMatchObject({ finger: 7, algorithm: 'pore-sift' })
    expect(server.verifications[1]!.runId).not.toBe(previous)
    act(() => server.emitVerification(VERIFIED, previous))
    expect(screen.queryByRole('heading', { name: he ? 'נמצאה התאמה לטביעת האצבע' : 'Fingerprint matches' })).toBeNull()
  })

  it('returns from method selection without starting or cancelling a scan', async () => {
    server.fingers = [7]
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Verify this finger (1:1)' }))
    fireEvent.click(await screen.findByRole('radio', { name: 'Learned pore descriptor' }))
    fireEvent.click(screen.getByRole('button', { name: 'Back to the fingers' }))
    expect(screen.getByRole('button', { name: 'Enrol this finger again' })).toBeTruthy()
    expect(server.verifications).toEqual([])
    expect(server.verificationCancels).toEqual([])
  })

  it('labels the demonstrated template and separates approval from the other methods’ pair scores', async () => {
    server.enrolment = [STARTED, kept(1, []), kept(2, []), kept(3, []), {
      ...SAVED,
      pending_methods: [],
      prepared_methods: [{ algorithm: 'pore-sift', templates: 3 }, { algorithm: 'learned-pore', templates: 3 }],
      method_comparisons: [
        { algorithm: 'opencv-sift', threshold: 57, threshold_provisional: false, pairs: SAVED.pairs },
        { algorithm: 'pore-sift', threshold: 37, threshold_provisional: true,
          pairs: SAVED.pairs.map((p) => ({ ...p, score: 0, accepted: false })) },
        { algorithm: 'learned-pore', threshold: 21, threshold_provisional: true,
          pairs: SAVED.pairs.map((p) => ({ ...p, score: 30, accepted: true })) },
      ],
    }]
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Left hand' })).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Enrol this finger' }))
    await screen.findByRole('heading', { name: 'How your fingerprint is stored' })
    expect(screen.getByText('Templates stored for: OpenCV SIFT, Pore SIFT, Learned pore descriptor.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'The points' }))
    expect(screen.getByText('Template demonstration: OpenCV SIFT')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Why it was accepted' }))
    expect(screen.getByRole('heading', { name: 'Enrolment check: OpenCV SIFT' })).toBeTruthy()
    const pore = screen.getByRole('region', { name: 'Pore SIFT' })
    expect(within(pore).getAllByText('not above 37')).toHaveLength(3)
    const learned = screen.getByRole('region', { name: 'Learned pore descriptor' })
    expect(within(learned).getAllByText('above 21: match')).toHaveLength(3)
    expect(screen.queryByRole('radio')).toBeNull()
  })
})

const IDENTIFIED: IdentificationEvent = {
  type: 'identified', attempt_id: '00000000-0000-4000-8000-000000000041', at: '2026-11-07T16:00:00Z',
  algorithm: 'opencv-sift', score: 90, threshold: 57, threshold_origin: 'SD302 plain vs plain', threshold_provisional: false,
  accepted: true, duration_ms: 710, gallery_size: 6, enrolments: 2, tied_leaders: 1,
  candidates: [
    { rank: 1, own: false, finger: null, score: 90, accepted: true },
    { rank: 2, own: true, finger: 7, score: 5, accepted: false },
  ],
}

describe('fingerprint identification (H41)', () => {
  it.each(['en', 'he'] as const)('identifies without a chosen finger and shows anonymous ranks in %s', async (language) => {
    const he = language === 'he'
    server.current = server.add('dana', 'user', { language })
    server.fingers = [7]
    server.identification = [IDENTIFIED]
    open('/fingerprint', true)
    fireEvent.click(await screen.findByRole('button', { name: he ? 'זיהוי טביעת אצבע (1:N)' : 'Identify a fingerprint (1:N)' }))
    expect(server.identifications).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת הזיהוי' : 'Start identification' }))
    expect(await screen.findByRole('heading', { name: he ? 'נמצאה טביעת אצבע תואמת' : 'A matching fingerprint was found' })).toBeTruthy()
    expect(server.identifications).toHaveLength(1)
    expect(server.identificationCancels).toEqual([])
    expect(screen.getAllByText(he ? 'משתמש רשום אחר' : 'Another registered user')).toHaveLength(2)
    expect(screen.getByText(he ? 'האצבע שלך: מורה שמאל' : 'Your left index')).toBeTruthy()
    expect(screen.getByRole('meter')).toHaveProperty('value', 90)
    expect(document.documentElement.dir).toBe(he ? 'rtl' : 'ltr')
    const previous = server.identifications[0]!
    server.identification = [{ type: 'searching', completed: 4, total: 6 }]
    fireEvent.click(screen.getByRole('button', { name: he ? 'זיהוי נוסף' : 'Identify again' }))
    await waitFor(() => expect(server.identifications).toHaveLength(2))
    expect(server.identifications[1]).not.toBe(previous)
    act(() => server.emitIdentification(IDENTIFIED, previous))
    expect(screen.queryByRole('meter')).toBeNull()
  })

  it.each(['en', 'he'] as const)('draws only the caller’s own highest-ranked print (H45) in %s', async (language) => {
    const he = language === 'he'
    const data = new Uint8Array(16)
    ;[10, 20, 30, 40].forEach((value, index) => new DataView(data.buffer).setFloat32(index * 4, value, true))
    server.current = server.add('dana', 'user', { language })
    server.fingers = [7]
    server.identification = [{ type: 'captured', image: 'PROBE', checks: CHECKS }, {
      ...IDENTIFIED, match_view: { rank: 2, finger: 7, placement: 3, reference_image: 'OWN', count: 1, pairs: btoa(String.fromCharCode(...data)) },
    }]
    open('/fingerprint', true)
    fireEvent.click(await screen.findByRole('button', { name: he ? 'זיהוי טביעת אצבע (1:N)' : 'Identify a fingerprint (1:N)' }))
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת הזיהוי' : 'Start identification' }))
    expect(await screen.findByText(he ? /לאצבע שלך: מורה שמאל, במקום 2 ברשימה/ : /with your left index, rank 2 in the list/)).toBeTruthy()
    const drawing = screen.getByRole('img', { name: he ? 'טביעת האצבע החדשה והשמורה עם 1 זוגות נקודות תואמות' : 'New and stored fingerprints with 1 matched point pairs' })
    expect([...drawing.querySelectorAll('image')].map((image) => image.getAttribute('href'))).toEqual([
      'data:image/png;base64,PROBE', 'data:image/png;base64,OWN',
    ])
    expect(drawing.querySelector('.match-connections')?.getAttribute('d')).toBe('M10 20L1130 40')
    expect(screen.queryByText(he ? /אף אחת מהטביעות שלך/ : /None of your own prints/)).toBeNull()
  })

  it('explains the missing drawing when none of the shown candidates is the caller’s', async () => {
    server.fingers = [7]
    server.identification = [{ type: 'captured', image: 'PROBE', checks: CHECKS }, {
      ...IDENTIFIED, candidates: [{ rank: 1, own: false, finger: null, score: 90, accepted: true }],
    }]
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start identification' }))
    expect(await screen.findByText('None of your own prints is among the candidates shown, so there is no drawing. Other users’ prints are never drawn.')).toBeTruthy()
    expect(screen.queryByRole('img', { name: /matched point pairs/ })).toBeNull()
  })

  it('requires enrolment before starting identification', async () => {
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    expect(screen.getByText('Enrol at least one of your fingers before using fingerprint identification.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Back to home' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Choose a finger to enrol' }))
    expect(await screen.findByRole('group', { name: 'Left hand' })).toBeTruthy()
    expect(server.identifications).toEqual([])
  })

  it('reports real progress, cancels on navigation and ignores the old result', async () => {
    server.fingers = [7]
    server.identification = [
      { type: 'started', algorithm: 'opencv-sift', threshold: 57, quality_minimum: 35, gallery_size: 9, enrolments: 3 },
      { type: 'searching', completed: 4, total: 9 },
    ]
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start identification' }))
    await screen.findByText('Compared 4 of 9 stored templates…')
    expect(screen.getByRole('progressbar')).toHaveProperty('value', 4)
    expect(screen.getByRole('progressbar')).toHaveProperty('max', 9)
    const previous = server.identifications[0]!
    fireEvent.click(screen.getByRole('link', { name: 'Home' }))
    expect(server.identificationCancels).toEqual([previous])
    fireEvent.click(await screen.findByRole('link', { name: 'Open' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    act(() => server.emitIdentification(IDENTIFIED, previous))
    expect(screen.queryByText('A matching fingerprint was found')).toBeNull()
    expect(screen.getByRole('button', { name: 'Start identification' })).toBeTruthy()
  })

  it('allows cancellation and a new run after a quality retry', async () => {
    server.fingers = [7]
    server.identification = [{ type: 'rejected', image: 'AAAA', checks: CHECKS, score: 20, minimum: 35 }, { type: 'lift' }]
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start identification' }))
    await screen.findByText(/The quality is 20, below the minimum of 35/)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('Identification cancelled.')).toBeTruthy()
    expect(screen.queryByRole('meter')).toBeNull()
    server.identification = [{ ...IDENTIFIED, accepted: false, score: 57,
      candidates: IDENTIFIED.candidates.map((c) => ({ ...c, score: 57, accepted: false })) }]
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'No matching fingerprint was found' })).toBeTruthy()
    expect(screen.getByText('The result and its encrypted capture were saved.')).toBeTruthy()
  })

  it('explains tied leaders and gallery changes', async () => {
    server.fingers = [7]
    server.identification = [{ ...IDENTIFIED, tied_leaders: 2 }]
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start identification' }))
    expect(await screen.findByText('2 candidates share the highest score. The result does not select a unique candidate.')).toBeTruthy()
    server.identification = [{ type: 'failed', error: 'gallery_changed' }]
    fireEvent.click(screen.getByRole('button', { name: 'Identify again' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'A searched enrolment or account changed. Start a new search to use the current registrations.')
    expect(screen.queryByRole('meter')).toBeNull()
  })
})

describe('pore-method identification (H42)', () => {
  it.each([
    ['pore-sift', 'en'], ['learned-pore', 'en'], ['pore-sift', 'he'], ['learned-pore', 'he'],
  ] as const)('chooses %s in %s, prepares templates and changes method before a fresh scan', async (algorithm, language) => {
    const he = language === 'he'
    const name = algorithm === 'pore-sift' ? 'Pore SIFT' : he ? 'המתאר הנלמד' : 'Learned pore descriptor'
    const threshold = algorithm === 'pore-sift' ? 37 : 21
    const score = algorithm === 'pore-sift' ? 45 : 30
    server.current = server.add('dana', 'user', { language })
    server.fingers = [7]
    server.identification = [
      { type: 'started', algorithm, threshold, quality_minimum: 35, gallery_size: 6, enrolments: 2 },
      { type: 'preparing_templates', algorithm, completed: 1, total: 3 },
    ]
    open('/fingerprint', true)
    fireEvent.click(await screen.findByRole('button', { name: he ? 'זיהוי טביעת אצבע (1:N)' : 'Identify a fingerprint (1:N)' }))
    expect(screen.getByRole('radio', { name: 'OpenCV SIFT' })).toHaveProperty('checked', true)
    fireEvent.click(screen.getByRole('radio', { name }))
    expect(server.identifications).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת הזיהוי' : 'Start identification' }))
    await waitFor(() => expect(server.identificationMethods).toEqual([algorithm]))
    expect(await screen.findByText(he ? `יוצרים תבניות ${name} (1 מתוך 3)…` : `Creating ${name} templates (1 of 3)…`)).toBeTruthy()
    expect(screen.getByRole('progressbar')).toHaveProperty('value', 1)
    expect(screen.getByRole('progressbar')).toHaveProperty('max', 3)
    const previous = server.identifications[0]!
    act(() => server.emitIdentification({ ...IDENTIFIED, algorithm, threshold, score, threshold_provisional: true }))
    expect(await screen.findByRole('meter', { name: he ? 'נקבוביות תואמות' : 'Matching pores' })).toHaveProperty('value', score)
    expect(screen.getByText(he ? /הסף הזה זמני בסורק HiScan PRO/ : /This threshold is provisional on the HiScan PRO/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: he ? 'החלפת שיטה' : 'Change method' }))
    expect(screen.getByRole('radio', { name })).toHaveProperty('checked', true)
    expect(server.identifications).toHaveLength(1)
    expect(server.identificationCancels).toEqual([])
    fireEvent.click(screen.getByRole('radio', { name: 'OpenCV SIFT' }))
    server.identification = [{ type: 'place', capture: 1, maximum: 12 }]
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת הזיהוי' : 'Start identification' }))
    await waitFor(() => expect(server.identificationMethods).toEqual([algorithm, 'opencv-sift']))
    expect(server.identifications[1]).not.toBe(previous)
    act(() => server.emitIdentification(IDENTIFIED, previous))
    expect(screen.queryByRole('meter')).toBeNull()
  })

  it('shows unavailable pore runtimes disabled while OpenCV SIFT stays selectable', async () => {
    server.fingers = [7]
    server.poreAvailable = server.learnedAvailable = false
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    expect(screen.getByRole('radio', { name: 'Pore SIFT' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('radio', { name: 'Learned pore descriptor' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('radio', { name: 'OpenCV SIFT' })).toHaveProperty('checked', true)
    expect(screen.getByRole('button', { name: 'Start identification' })).toHaveProperty('disabled', false)
    expect(server.identifications).toEqual([])
  })

  it('cancels gallery preparation and retries with the same method', async () => {
    server.fingers = [7]
    server.identification = [{ type: 'preparing_templates', algorithm: 'learned-pore', completed: 2, total: 6 }]
    await openFingerprint()
    fireEvent.click(screen.getByRole('button', { name: 'Identify a fingerprint (1:N)' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Learned pore descriptor' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start identification' }))
    await screen.findByText('Creating Learned pore descriptor templates (2 of 6)…')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await screen.findByText('Identification cancelled.')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(server.identificationMethods).toEqual(['learned-pore', 'learned-pore']))
    expect(screen.queryByRole('meter')).toBeNull()
  })
})

describe('OpenCV SIFT match illustration (H43)', () => {
  const coordinates = [10, 20, 30, 40, 800, 900, 700, 600]
  const data = new Uint8Array(coordinates.length * 4)
  coordinates.forEach((value, index) => new DataView(data.buffer).setFloat32(index * 4, value, true))
  const encoded = btoa(String.fromCharCode(...data))

  it.each(['en', 'he'] as const)('shows the winning image and counted pairs with keyboard controls in %s', async (language) => {
    const he = language === 'he'
    server.current = server.add('dana', 'user', { language })
    server.fingers = [7]
    server.verification = [{ type: 'captured', image: 'PROBE', checks: CHECKS }, {
      ...VERIFIED, score: 2, threshold: 1,
      match_view: { placement: 2, reference_image: 'REFERENCE', count: 2, pairs: encoded },
    }]
    open('/fingerprint')
    fireEvent.click(within(await screen.findByRole('group', { name: he ? 'יד שמאל' : 'Left hand' })).getByRole('button', { name: he ? /מורה/ : /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: he ? 'אימות האצבע הזו (1:1)' : 'Verify this finger (1:1)' }))
    fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת האימות' : 'Start verification' }))
    const drawing = await screen.findByRole('img', { name: he ? 'טביעת האצבע החדשה והשמורה עם 2 זוגות נקודות תואמות' : 'New and stored fingerprints with 2 matched point pairs' })
    expect([...drawing.querySelectorAll('image')].map((image) => image.getAttribute('href'))).toEqual([
      'data:image/png;base64,PROBE', 'data:image/png;base64,REFERENCE',
    ])
    expect(drawing.querySelector('.match-connections')?.getAttribute('d')).toBe('M10 20L1130 40 M800 900L1800 600')
    const slider = screen.getByRole('slider', { name: he ? 'בחירת הזוג המודגש' : 'Choose the highlighted pair' })
    fireEvent.change(slider, { target: { value: '2' } })
    expect(drawing.querySelector('.match-selected path:not(.match-halo)')?.getAttribute('d')).toBe('M800 900L1800 600')
    fireEvent.click(screen.getByRole('checkbox', { name: he ? 'הצגת כל זוגות הנקודות התואמות' : 'Show all matching pairs' }))
    expect(drawing.querySelector('.match-connections')).toBeNull()
    expect(drawing.querySelectorAll('.match-selected circle')).toHaveLength(2)
    server.verification = [{ type: 'place', capture: 1, maximum: 12 }]
    fireEvent.click(screen.getByRole('button', { name: he ? 'אימות נוסף' : 'Verify again' }))
    await waitFor(() => expect(screen.queryByRole('slider')).toBeNull())
    expect(document.querySelector('image[href="data:image/png;base64,REFERENCE"]')).toBeNull()
  })

  it('shows a zero-score comparison without drawing any match', async () => {
    server.fingers = [7]
    server.verification = [{ type: 'captured', image: 'PROBE', checks: CHECKS }, {
      ...VERIFIED, score: 0, accepted: false, match_view: { placement: 1, reference_image: 'REFERENCE', count: 0, pairs: '' },
    }]
    await startVerification()
    expect(await screen.findByText('No point pairs contributed to this comparison’s score.')).toBeTruthy()
    expect(screen.getByText(/as RANSAC requires/)).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()
    expect(document.querySelectorAll('.match-selected circle')).toHaveLength(0)
  })
})

describe('pore match illustrations (H44)', () => {
  const coordinates = [120, 700, 130, 690, 400, 300, 410, 310]
  const data = new Uint8Array(coordinates.length * 4)
  coordinates.forEach((value, index) => new DataView(data.buffer).setFloat32(index * 4, value, true))
  const encoded = btoa(String.fromCharCode(...data))

  it.each([['pore-sift', 'Pore SIFT', 'en'], ['learned-pore', 'המתאר הנלמד', 'he']] as const)(
    'names the pores of %s and how they are counted', async (algorithm, method, language) => {
      const he = language === 'he'
      server.current = server.add('dana', 'user', { language })
      server.fingers = [7]
      server.verification = [{ type: 'captured', image: 'PROBE', checks: CHECKS }, {
        ...VERIFIED, algorithm, score: 2, threshold: 1,
        match_view: { placement: 3, reference_image: 'REFERENCE', count: 2, pairs: encoded },
      }]
      open('/fingerprint')
      fireEvent.click(within(await screen.findByRole('group', { name: he ? 'יד שמאל' : 'Left hand' })).getByRole('button', { name: he ? /מורה/ : /Index/ }))
      fireEvent.click(screen.getByRole('button', { name: he ? 'אימות האצבע הזו (1:1)' : 'Verify this finger (1:1)' }))
      fireEvent.click(await screen.findByRole('radio', { name: method }))
      fireEvent.click(screen.getByRole('button', { name: he ? 'התחלת האימות' : 'Start verification' }))
      expect(await screen.findByRole('heading', { name: he ? 'התאמות הנקבוביות בהשוואה הזו' : 'Pore matches in this comparison' })).toBeTruthy()
      expect(server.verifications[0]?.algorithm).toBe(algorithm)
      const drawing = screen.getByRole('img', { name: he ? 'טביעת האצבע החדשה והשמורה עם 2 זוגות נקבוביות תואמות' : 'New and stored fingerprints with 2 matched pore pairs' })
      expect(drawing.querySelector('.match-connections')?.getAttribute('d')).toBe('M120 700L1230 690 M400 300L1510 310')
      expect(screen.getByText(he ? /חלק מהקווים עשויים להצטלב/ : /so some lines may cross/)).toBeTruthy()
      expect(screen.getByText(he ? 'הנחה שמורה 3' : 'Stored placement 3')).toBeTruthy()
      fireEvent.click(screen.getByRole('checkbox', { name: he ? 'הצגת כל זוגות הנקבוביות התואמות' : 'Show all matching pore pairs' }))
      expect(drawing.querySelector('.match-connections')).toBeNull()
      expect(drawing.querySelectorAll('.match-selected circle')).toHaveLength(2)
    })
})

describe('deleting a finger’s enrolment (H34)', () => {
  it('asks first, then deletes it without a new enrolment', async () => {
    server.fingers = [2, 7]
    await openFingerprint()
    const left = screen.getByRole('group', { name: 'Left hand' })
    expect(within(left).getByRole('button', { name: /Index/ }).textContent).toContain('enrolled')
    fireEvent.click(within(left).getByRole('button', { name: /Index/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete this finger’s enrolment' }))
    expect(screen.getByRole('alertdialog').textContent).toContain('Delete the enrolment of the left index?')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(server.fingers).toEqual([2, 7])
    fireEvent.click(screen.getByRole('button', { name: 'Delete this finger’s enrolment' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText(/The enrolment of the left index was deleted/)).toBeTruthy()
    expect(server.fingers).toEqual([2])
    await waitFor(() => expect(within(left).getByRole('button', { name: 'Index' }).textContent).toBe('Index'))
    expect(screen.getByRole('button', { name: 'Enrol this finger' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Delete this finger’s enrolment' })).toBeNull()
    expect(server.enrolments).toEqual([])
  })

  it('offers no deletion for a finger that is not enrolled', async () => {
    await openFingerprint()
    fireEvent.click(within(screen.getByRole('group', { name: 'Right hand' })).getByRole('button', { name: 'Thumb' }))
    expect(screen.getByRole('button', { name: 'Enrol this finger' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Delete this finger’s enrolment' })).toBeNull()
  })
})
