import { describe, expect, it } from 'vitest'
import type { Session } from 'electron'
import { appPageMatcher, permitCamera } from './window'

type RequestHandler = (contents: { getURL(): string }, permission: string, callback: (granted: boolean) => void, details: object) => void
type CheckHandler = (contents: null, permission: string, origin: string, details: object) => boolean

function handlers(appPage: (url: string) => boolean) {
  let request: RequestHandler | null = null
  let check: CheckHandler | null = null
  const session = {
    setPermissionRequestHandler: (handler: RequestHandler) => { request = handler },
    setPermissionCheckHandler: (handler: CheckHandler) => { check = handler },
  } as unknown as Session
  permitCamera(session, appPage)
  const asked = (permission: string, details: object, url = 'file:///app/out/renderer/index.html') => {
    let granted: boolean | null = null
    request!({ getURL: () => url }, permission, (value) => { granted = value }, details)
    return granted
  }
  return { asked, checked: (permission: string, origin: string, details: object) => check!(null, permission, origin, details) }
}

describe('the camera permission (H48)', () => {
  const page = 'file:///app/out/renderer/index.html'
  const { asked, checked } = handlers(appPageMatcher(undefined))

  it('grants the camera to the app page, for video only', () => {
    expect(asked('media', { mediaTypes: ['video'], requestingUrl: page })).toBe(true)
    expect(checked('media', 'file://', { mediaType: 'video' })).toBe(true)
  })

  it('refuses the microphone, other permissions and other pages', () => {
    expect(asked('media', { mediaTypes: ['audio'], requestingUrl: page })).toBe(false)
    expect(asked('media', { mediaTypes: ['video', 'audio'], requestingUrl: page })).toBe(false)
    expect(asked('media', { mediaTypes: [], requestingUrl: page })).toBe(false)
    expect(asked('notifications', { requestingUrl: page })).toBe(false)
    expect(asked('media', { mediaTypes: ['video'], requestingUrl: 'https://example.org/' })).toBe(false)
    expect(checked('media', 'file://', { mediaType: 'audio' })).toBe(false)
    expect(checked('geolocation', 'file://', {})).toBe(false)
    expect(checked('media', 'https://example.org', { mediaType: 'video' })).toBe(false)
  })

  it('knows the development server by its origin', () => {
    const matches = appPageMatcher('http://localhost:5173')
    expect(matches('http://localhost:5173/index.html')).toBe(true)
    expect(matches('http://localhost:5174/')).toBe(false)
    expect(matches('file:///app/index.html')).toBe(false)
    expect(matches('not a url')).toBe(false)
  })
})
