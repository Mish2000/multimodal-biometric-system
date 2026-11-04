/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { Account, ApiResult, Language, MbsBridge, OpenedLink, RouteName, Theme } from '../../shared/bridge'
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

  call = async <T,>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>> =>
    this.answer(route, (body ?? {}) as Record<string, string>, id) as ApiResult<T>

  private answer(route: RouteName, body: Record<string, string>, id?: string): ApiResult {
    const ok = (data: unknown = null): ApiResult => ({ ok: true, data })
    const no = (status: number, error: string): ApiResult => ({ ok: false, status, error })
    if (!this.up) return no(0, 'server_unreachable')
    switch (route) {
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
        const modalities = { fingerprint: { enrolled: false }, face: { enrolled: false }, voice: { enrolled: false } }
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

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  )
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
    expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual(['Home', 'Settings'])
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
