import { describe, expect, it } from 'vitest'
import { decodeMatchPairs, nearestMatch } from './match-data'

function encode(values: number[]): string {
  const bytes = new Uint8Array(values.length * 4)
  const data = new DataView(bytes.buffer)
  values.forEach((value, index) => data.setFloat32(index * 4, value, true))
  return btoa(String.fromCharCode(...bytes))
}

describe('match coordinates (H43)', () => {
  it('decodes the native pixel coordinates and selects on either image without swapping the axes', () => {
    const pairs = decodeMatchPairs(encode([10.5, 20.25, 130, 140, 900, 800, 30, 40]), 2)!
    expect(Array.from(pairs)).toEqual([10.5, 20.25, 130, 140, 900, 800, 30, 40])
    expect(nearestMatch(pairs, 11, 20, false)).toBe(0)
    expect(nearestMatch(pairs, 31, 41, true)).toBe(1)
  })
  it('accepts a zero-score illustration with no pairs', () => {
    expect(decodeMatchPairs('', 0)).toEqual(new Float32Array())
    expect(nearestMatch(new Float32Array(), 0, 0, false)).toBe(-1)
  })
  it('rejects truncated, non-finite and out-of-image coordinates', () => {
    expect(decodeMatchPairs(encode([1, 2, 3, 4]), 2)).toBeNull()
    expect(decodeMatchPairs(encode([1, 2, NaN, 4]), 1)).toBeNull()
    expect(decodeMatchPairs(encode([1, 2, 3, 1000]), 1)).toBeNull()
    expect(decodeMatchPairs('?', 1)).toBeNull()
  })
})
