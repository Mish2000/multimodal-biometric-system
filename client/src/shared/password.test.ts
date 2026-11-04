import { describe, expect, it } from 'vitest'
import { checkPassword } from './password'

// The same examples as the server's rules (server/tests/test_security.py), plus the meter's levels (H30).
describe('checkPassword', () => {
  it.each([
    ['ABCDEFG1', 'weak'],
    ['Abcdefg1', 'medium'],
    ['ABCDEFG1!', 'medium'],
    ['Passw0rd!', 'strong'],
    ['Two words 1', 'strong'],
    ['סיסמהAB1', 'weak'],
    ['Ａbcdefg１', 'medium'],
    ['A1' + 'x'.repeat(30), 'medium'],
  ])('accepts %s as %s', (password, strength) => {
    expect(checkPassword(password).strength).toBe(strength)
  })

  it.each(['Abcdef1', 'A1' + 'x'.repeat(31), 'abcdefg1', 'ABCDEFGH', 'סיסמה12345', ''])('finds %s invalid', (password) => {
    expect(checkPassword(password).strength).toBe('invalid')
  })

  it('counts characters as the server does, not UTF-16 units', () => {
    expect(checkPassword('A1😀😀😀😀😀😀').length).toBe(true)
    expect(checkPassword('A1' + '😀'.repeat(30)).length).toBe(true)
    expect(checkPassword('A1' + '😀'.repeat(31)).length).toBe(false)
  })

  it('says which rule is missing', () => {
    expect(checkPassword('abc')).toEqual({ length: false, uppercase: false, digit: false, lowercase: true, special: false, strength: 'invalid' })
  })
})
