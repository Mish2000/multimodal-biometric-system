/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { Account, ApiResult, MbsBridge, RouteName, Theme } from '../../shared/bridge'
import { App } from './App'
import { SessionProvider } from './session'

interface Stored extends Account {
  password: string
  status: 'active' | 'disabled'
}

const view = ({ password: _password, status: _status, ...account }: Stored): Account => account

// The server as the page sees it through the bridge, in memory: as much of the API as the screens use.
class FakeServer implements MbsBridge {
  accounts: Stored[] = []
  current: Stored | null = null
  up = true
  themes: Theme[] = []

  add(username: string, role: Account['role'], extra: Partial<Stored> = {}): Stored {
    const account: Stored = {
      id: `00000000-0000-4000-8000-${String(this.accounts.length + 1).padStart(12, '0')}`,
      username,
      email: `${username}@example.com`,
      role,
      must_change_password: false,
      theme: 'system',
      password: `${username} password 1`,
      status: 'active',
      ...extra,
    }
    this.accounts.push(account)
    return account
  }

  setTheme = (theme: Theme): void => {
    this.themes.push(theme)
  }

  call = async <T,>(route: RouteName, body?: unknown, id?: string): Promise<ApiResult<T>> =>
    this.answer(route, (body ?? {}) as Record<string, string>, id) as ApiResult<T>

  private answer(route: RouteName, body: Record<string, string>, id?: string): ApiResult {
    const ok = (data: unknown = null): ApiResult => ({ ok: true, data })
    const no = (status: number, error: string): ApiResult => ({ ok: false, status, error })
    if (!this.up) return no(0, 'server_unreachable')
    if (route === 'health') return ok({ status: 'ok' })
    if (route === 'register') {
      if (this.accounts.some((a) => a.username === body.username)) return no(409, 'username_taken')
      return ok({ account: view(this.add(body.username ?? '', 'user', { email: body.email ?? '', password: body.password ?? '' })) })
    }
    if (route === 'login') {
      const found = this.accounts.find((a) => (a.username === body.login || a.email === body.login) && a.password === body.password)
      if (found === undefined) return no(401, 'wrong_credentials')
      if (found.status === 'disabled') return no(403, 'account_disabled')
      this.current = found
      return ok({ account: view(found) })
    }
    if (route === 'logout') {
      this.current = null
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

async function signIn(login: string, password: string) {
  const button = await screen.findByRole('button', { name: 'כניסה' })
  type('שם משתמש או אימייל', login)
  type('סיסמה', password)
  fireEvent.click(button)
}

describe('the navigation', () => {
  it('signs a user in to the home screen and out again', async () => {
    server.add('dana', 'user', { theme: 'light' })
    open('/')
    await signIn('dana', 'dana password 1')
    expect(await screen.findByRole('heading', { name: 'שלום, dana' })).toBeTruthy()
    expect(await screen.findAllByText('עוד לא נרשם')).toHaveLength(3)
    for (const name of ['טביעת אצבע', 'פנים', 'קול']) expect(screen.getByRole('heading', { name })).toBeTruthy()
    await waitFor(() => expect(server.themes).toEqual(['system', 'light']))
    fireEvent.click(screen.getByRole('button', { name: 'יציאה' }))
    expect(await screen.findByRole('button', { name: 'כניסה' })).toBeTruthy()
    expect(server.current).toBeNull()
    await waitFor(() => expect(server.themes.at(-1)).toBe('system'))
  })

  it('words wrong credentials and a disabled account in Hebrew', async () => {
    server.add('dana', 'user', { status: 'disabled' })
    open('/sign-in')
    await signIn('dana', 'not her password')
    expect(await screen.findByText('שם המשתמש או הסיסמה שגויים.')).toBeTruthy()
    await signIn('dana', 'dana password 1')
    expect(await screen.findByText('החשבון הזה מושבת. אפשר לפנות למנהל המערכת.')).toBeTruthy()
  })

  it('says when the server is down, and checks again', async () => {
    server.up = false
    open('/sign-in')
    expect(await screen.findByText(/השרת לא פועל/)).toBeTruthy()
    server.up = true
    fireEvent.click(screen.getByRole('button', { name: 'לבדוק שוב' }))
    await waitFor(() => expect(screen.queryByText(/השרת לא פועל/)).toBeNull())
  })

  it('signs a new account in after registration', async () => {
    open('/register')
    await screen.findByRole('heading', { name: 'חשבון חדש' })
    type('שם משתמש', 'noa')
    type('אימייל', 'noa@example.com')
    type('סיסמה', 'a long password 1')
    type('מספר זהות', '000000018')
    fireEvent.click(screen.getByRole('button', { name: 'יצירת החשבון' }))
    expect(await screen.findByRole('heading', { name: 'שלום, noa' })).toBeTruthy()
  })

  it('keeps an administrator with a one-time password on the password screen until it is replaced', async () => {
    server.add('admin', 'admin', { must_change_password: true, password: 'one-time-1' })
    server.add('dana', 'user')
    open('/admin')
    await signIn('admin', 'one-time-1')
    expect(await screen.findByRole('heading', { name: 'בחירת סיסמה חדשה' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'אזור הניהול' })).toBeNull()
    type('הסיסמה החד-פעמית', 'one-time-1')
    type('סיסמה חדשה', 'a new long password')
    type('הסיסמה החדשה שוב', 'another long password')
    fireEvent.click(screen.getByRole('button', { name: 'שמירה' }))
    expect(await screen.findByText('שתי הסיסמאות החדשות לא זהות.')).toBeTruthy()
    type('הסיסמה החדשה שוב', 'a new long password')
    fireEvent.click(screen.getByRole('button', { name: 'שמירה' }))
    expect(await screen.findByRole('heading', { name: 'אזור הניהול', level: 1 })).toBeTruthy()
    expect(await screen.findByRole('row', { name: /dana/ })).toBeTruthy()
  })

  it('sends a user who opens the administration area home, with the session the main process kept', async () => {
    server.current = server.add('dana', 'user')
    open('/admin')
    expect(await screen.findByRole('heading', { name: 'שלום, dana' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'אזור הניהול' })).toBeNull()
  })

  it('returns to sign-in with a notice when the server has ended the session', async () => {
    server.current = server.add('dana', 'user')
    open('/settings')
    const dark = await screen.findByLabelText('כהה')
    server.current = null
    fireEvent.click(dark)
    expect(await screen.findByText('הכניסה הסתיימה. צריך להיכנס שוב.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'כניסה' })).toBeTruthy()
  })
})

describe('the settings', () => {
  it("save the account's theme and apply it to the window", async () => {
    const dana = server.add('dana', 'user')
    server.current = dana
    open('/settings')
    fireEvent.click(await screen.findByLabelText('כהה'))
    await waitFor(() => expect(server.themes.at(-1)).toBe('dark'))
    expect(dana.theme).toBe('dark')
    expect((screen.getByLabelText('כהה') as HTMLInputElement).checked).toBe(true)
  })

  it('change the password in the security area, only with the current one (H28)', async () => {
    const dana = server.add('dana', 'user')
    server.current = dana
    open('/settings')
    expect(await screen.findByRole('heading', { name: 'אבטחה' })).toBeTruthy()
    type('הסיסמה הנוכחית', 'not her password')
    type('סיסמה חדשה', 'a new long password')
    type('הסיסמה החדשה שוב', 'a new long password')
    fireEvent.click(screen.getByRole('button', { name: 'החלפת הסיסמה' }))
    expect(await screen.findByText('הסיסמה שגויה.')).toBeTruthy()
    expect(dana.password).toBe('dana password 1')
    type('הסיסמה הנוכחית', 'dana password 1')
    fireEvent.click(screen.getByRole('button', { name: 'החלפת הסיסמה' }))
    expect(await screen.findByText('הסיסמה הוחלפה. הכניסות האחרות לחשבון נותקו.')).toBeTruthy()
    expect(dana.password).toBe('a new long password')
    expect((screen.getByLabelText('הסיסמה הנוכחית') as HTMLInputElement).value).toBe('')
  })

  it('have no password screen of their own: the bar has no link, and its old address leads home', async () => {
    server.current = server.add('dana', 'user')
    open('/password')
    expect(await screen.findByRole('heading', { name: 'שלום, dana' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'החלפת סיסמה' })).toBeNull()
    expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual(['מסך הבית', 'הגדרות'])
  })
})

describe('the administration area', () => {
  it('disables an account only after the administrator gives the password again', async () => {
    server.current = server.add('admin', 'admin')
    const dana = server.add('dana', 'user')
    open('/admin')
    const row = await screen.findByRole('row', { name: /dana/ })
    expect(within(screen.getByRole('row', { name: /admin@example\.com/ })).getByText('החשבון שלך')).toBeTruthy()
    fireEvent.click(within(row).getByRole('button', { name: 'השבתה…' }))
    type('הסיסמה שלך, לאישור', 'not the password', row)
    fireEvent.click(within(row).getByRole('button', { name: 'השבתה' }))
    expect(await within(row).findByText('הסיסמה שגויה.')).toBeTruthy()
    expect(dana.status).toBe('active')
    type('הסיסמה שלך, לאישור', 'admin password 1', row)
    fireEvent.click(within(row).getByRole('button', { name: 'השבתה' }))
    expect(await within(row).findByText('מושבת')).toBeTruthy()
    expect(dana.status).toBe('disabled')
  })

  it("shows a new administrator's one-time password once", async () => {
    server.current = server.add('admin', 'admin')
    open('/admin')
    const create = await screen.findByRole('button', { name: 'יצירה' })
    const form = create.closest('form') as HTMLFormElement
    type('שם משתמש', 'rotem', form)
    type('אימייל', 'rotem@example.com', form)
    type('הסיסמה שלך, לאישור', 'admin password 1', form)
    fireEvent.click(create)
    expect((await screen.findByRole('status')).textContent).toContain('one-time-Kq7xW2')
    expect(await screen.findByRole('row', { name: /rotem/ })).toBeTruthy()
  })
})
