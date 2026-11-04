// The password rules of H30, as the server checks them (server/mbs/passwords.py): counted after NFKC
// normalisation, in characters as Python counts them, 8 to 32 of them, with at least one uppercase letter
// and at least one digit. Lowercase letters and other characters (punctuation, symbols, spaces) are optional
// and make a password stronger: with neither it is weak, with one of the two medium, with both strong.
// Letters without case, such as Hebrew ones, count as neither.

export const MIN_LENGTH = 8
export const MAX_LENGTH = 32

export const STRENGTHS = ['invalid', 'weak', 'medium', 'strong'] as const
export type Strength = (typeof STRENGTHS)[number]

export interface PasswordCheck {
  length: boolean
  uppercase: boolean
  digit: boolean
  lowercase: boolean
  special: boolean
  strength: Strength
}

export function checkPassword(password: string): PasswordCheck {
  const text = password.normalize('NFKC')
  const characters = [...text].length
  const length = characters >= MIN_LENGTH && characters <= MAX_LENGTH
  const uppercase = /\p{Lu}/u.test(text)
  const digit = /\p{Nd}/u.test(text)
  const lowercase = /\p{Ll}/u.test(text)
  const special = /[^\p{L}\p{Nd}]/u.test(text)
  const valid = length && uppercase && digit
  const extras = Number(lowercase) + Number(special)
  const strength: Strength = !valid ? 'invalid' : extras === 0 ? 'weak' : extras === 1 ? 'medium' : 'strong'
  return { length, uppercase, digit, lowercase, special, strength }
}
