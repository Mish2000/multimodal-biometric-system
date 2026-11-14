/** @vitest-environment jsdom */
// A screen that fails while it renders shows a message instead of an empty window: inside the frame, which stays,
// and before sign-in; any move to a screen shows it again. Two screens are made to fail here on demand.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Account, ApiResult, MbsBridge, RouteName } from '../../shared/bridge'
import { App } from './App'
import { SessionProvider } from './session'

const failing = vi.hoisted(() => ({ settings: false, signIn: false }))

vi.mock('./pages/Settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./pages/Settings')>()
  const { createElement } = await import('react')
  return {
    Settings: () => {
      if (failing.settings) throw new Error('the settings screen failed')
      return createElement(actual.Settings)
    },
  }
})

vi.mock('./pages/SignIn', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./pages/SignIn')>()
  const { createElement } = await import('react')
  return {
    SignIn: () => {
      if (failing.signIn) throw new Error('the sign-in screen failed')
      return createElement(actual.SignIn)
    },
  }
})

const DANA: Account = {
  id: '0b0f6b9e-3c55-4d0e-9a51-4f0f2a7f1c11', username: 'dana', email: 'dana@example.com', role: 'user',
  must_change_password: false, theme: 'system', language: 'en',
}

// The server, as far as these screens ask it: who is signed in, and whether it runs.
class Bridge implements MbsBridge {
  constructor(private readonly account: Account | null) {}

  call = async <T,>(route: RouteName): Promise<ApiResult<T>> => {
    if (route === 'me' && this.account !== null) return { ok: true, data: { account: this.account, modalities: {} } as T }
    if (route === 'health') return { ok: true, data: { status: 'ok' } as T }
    return { ok: false, status: 401, error: 'not_signed_in' }
  }

  displays = async () => ({ internalDisplay: false })
  onDisplays = () => () => undefined
  setTheme = () => undefined
  takeLink = async () => null
  onLink = () => () => undefined
  enrolFingerprint = async (): Promise<ApiResult<null>> => ({ ok: true, data: null })
  cancelEnrolment = () => undefined
  onEnrolment = () => () => undefined
  verifyFingerprint = async (): Promise<ApiResult<null>> => ({ ok: true, data: null })
  cancelVerification = () => undefined
  onVerification = () => () => undefined
  identifyFingerprint = async (): Promise<ApiResult<null>> => ({ ok: true, data: null })
  cancelIdentification = () => undefined
  onIdentification = () => () => undefined
}

function open(path: string, account: Account | null) {
  window.mbs = new Bridge(account)
  render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  failing.settings = false
  failing.signIn = false
  vi.spyOn(console, 'error').mockImplementation(() => undefined) // React reports every error it catches
})

afterEach(cleanup)

describe('a screen that fails while it renders', () => {
  it('shows a message inside the frame, which stays, and goes back to the main screen', async () => {
    failing.settings = true
    open('/settings', DANA)
    expect(await screen.findByRole('heading', { name: 'This screen could not be shown' })).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toContain('restart the client')
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy()
    failing.settings = false
    fireEvent.click(screen.getByRole('button', { name: 'Back to the main screen' }))
    expect(await screen.findByRole('heading', { level: 1, name: /Hello/ })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('is shown again when its screen is chosen again', async () => {
    failing.settings = true
    open('/settings', DANA)
    await screen.findByRole('heading', { name: 'This screen could not be shown' })
    failing.settings = false
    fireEvent.click(screen.getByRole('link', { name: 'Settings' }))
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it("speaks the account's language", async () => {
    failing.settings = true
    open('/settings', { ...DANA, language: 'he' })
    expect(await screen.findByRole('heading', { name: 'לא ניתן היה להציג את המסך הזה' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'חזרה למסך הראשי' })).toBeTruthy()
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('covers the screens before sign-in too', async () => {
    failing.signIn = true
    open('/sign-in', null)
    expect(await screen.findByRole('heading', { name: 'This screen could not be shown' })).toBeTruthy()
    failing.signIn = false
    fireEvent.click(screen.getByRole('button', { name: 'Back to the main screen' }))
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
