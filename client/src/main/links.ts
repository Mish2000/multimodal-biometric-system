// The client's own link type (H32): a message to reset a password carries
// mbs://reset-password?token=...&lang=..., and Windows hands such a link to the client, on the command line
// of a new start or of a second start that passes it on to the running one.
import { LANGUAGES, type Language } from '../shared/bridge'

export const PROTOCOL = 'mbs'
const TOKEN = /^[A-Za-z0-9_-]{20,64}$/ // the server's random token, URL-safe base64

export interface ResetLink {
  token: string
  language: Language | null
}

export function parseResetLink(text: string): ResetLink | null {
  let url: URL
  try {
    url = new URL(text)
  } catch {
    return null
  }
  if (url.protocol !== `${PROTOCOL}:` || url.hostname !== 'reset-password') return null
  const token = url.searchParams.get('token') ?? ''
  if (!TOKEN.test(token)) return null
  const lang = url.searchParams.get('lang')
  return { token, language: LANGUAGES.includes(lang as Language) ? (lang as Language) : null }
}

// The first argument that is one of the client's links, if any (Electron's deep link guide).
export function findResetLink(args: readonly string[]): ResetLink | null {
  for (const arg of args) {
    if (arg.toLowerCase().startsWith(`${PROTOCOL}:`)) return parseResetLink(arg)
  }
  return null
}
