import { describe, expect, it } from 'vitest'
import { findResetLink, parseResetLink } from './links'

const TOKEN = 'k3J9_xQ-2mZ8vB1nL0pR7sT4uW6yA5cD9eF2gH3iJ4k'

describe('the client links (H32)', () => {
  it('reads the token and the language of a reset link', () => {
    expect(parseResetLink(`mbs://reset-password?token=${TOKEN}&lang=he`)).toEqual({ token: TOKEN, language: 'he' })
    expect(parseResetLink(`mbs://reset-password?token=${TOKEN}&lang=fr`)).toEqual({ token: TOKEN, language: null })
  })

  it('refuses anything else', () => {
    for (const text of [
      `https://reset-password?token=${TOKEN}`,
      `mbs://other?token=${TOKEN}`,
      'mbs://reset-password?token=short',
      `mbs://reset-password?token=${TOKEN}%22%3E`,
      'mbs://reset-password',
      'not a link',
    ]) {
      expect(parseResetLink(text)).toBeNull()
    }
  })

  it('finds the link among the arguments Windows passes', () => {
    const args = ['C:\\electron.exe', 'C:\\client', '--allow-file-access-from-files', `mbs://reset-password?token=${TOKEN}&lang=en`]
    expect(findResetLink(args)).toEqual({ token: TOKEN, language: 'en' })
    expect(findResetLink(['C:\\electron.exe', '.'])).toBeNull()
  })
})
