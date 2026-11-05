import { describe, expect, it } from 'vitest'
import { decodePoints, descriptorOf, heatmapLines, nearest, sealedBytes } from './data'

function base64(bytes: Uint8Array): string {
  let text = ''
  for (const b of bytes) text += String.fromCharCode(b)
  return btoa(text)
}

function points(xy: number[], descriptor: (point: number, index: number) => number) {
  const values = new Uint8Array((xy.length / 2) * 128)
  for (let p = 0; p < xy.length / 2; p++) for (let i = 0; i < 128; i++) values[p * 128 + i] = descriptor(p, i)
  return decodePoints(base64(new Uint8Array(new Float32Array(xy).buffer)), base64(values))
}

describe('the template screen data (H33)', () => {
  it('decodes the points and their 128-number descriptors', () => {
    const decoded = points([10.5, 20, 300, 400.25], (p, i) => (p * 7 + i) % 256)
    expect(decoded.count).toBe(2)
    expect(Array.from(decoded.xy)).toEqual([10.5, 20, 300, 400.25])
    expect(descriptorOf(decoded, 1)[0]).toBe(7)
    expect(descriptorOf(decoded, 1)).toHaveLength(128)
  })

  it('finds the point nearest to the pointer', () => {
    const decoded = points([0, 0, 100, 100, 500, 40], () => 0)
    expect(nearest(decoded, 90, 95)).toBe(1)
    expect(nearest(decoded, 480, 0)).toBe(2)
    expect(nearest(points([], () => 0), 1, 1)).toBe(-1)
  })

  it('draws groups of points as one line of their means', () => {
    const decoded = points([0, 0, 1, 1, 2, 2, 3, 3, 4, 4], (p) => p * 10)
    const { rows, height, values } = heatmapLines(decoded, 2)
    expect(rows).toBe(3)
    expect(height).toBe(2)
    expect(values[0]).toBe(10) // points 0, 1, 2
    expect(values[128]).toBe(35) // points 3, 4
  })

  it('splits a sealed value into its parts', () => {
    const head = new Uint8Array(50 + 48).map((_, i) => i)
    const parts = sealedBytes({
      length: 50 + 1000 + 16, head: base64(head), tag: base64(new Uint8Array(16).fill(255)),
      magic: 4, version: 2, salt: 32, nonce: 12, ciphertext: 1000, tag_bytes: 16,
    })
    expect(parts.map((p) => [p.part, p.hex.length, p.total])).toEqual([
      ['magic', 4, 4], ['version', 2, 2], ['salt', 32, 32], ['nonce', 12, 12], ['ciphertext', 48, 1000], ['tag', 16, 16],
    ])
    expect(parts[1]?.hex).toEqual(['04', '05'])
    expect(parts[5]?.hex[0]).toBe('ff')
  })
})
