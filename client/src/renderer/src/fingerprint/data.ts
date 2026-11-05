// The template screen's data (H33), decoded in the page: the server sends it once, in base64, and nothing of
// it is kept after the screen closes.
import type { SealedLayout } from '../../../shared/bridge'

export const DESCRIPTOR_LENGTH = 128
export const SIFT_CELLS = 4 // SIFT's descriptor: 4 x 4 cells around the point...
export const SIFT_BINS = 8 // ...with 8 orientation bins each (OpenCV's order: cell row, cell column, bin)

export function fromBase64(text: string): Uint8Array {
  const binary = atob(text)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

export interface Points {
  count: number
  xy: Float32Array // x, y per point, in the capture's pixels
  descriptors: Uint8Array // 128 per point
}

export function decodePoints(points: string, descriptors: string): Points {
  const raw = fromBase64(points)
  const xy = new Float32Array(raw.buffer, raw.byteOffset, Math.floor(raw.byteLength / 4))
  const values = fromBase64(descriptors)
  return { count: Math.min(xy.length / 2, values.length / DESCRIPTOR_LENGTH), xy, descriptors: values }
}

export function descriptorOf(points: Points, index: number): Uint8Array {
  return points.descriptors.subarray(index * DESCRIPTOR_LENGTH, (index + 1) * DESCRIPTOR_LENGTH)
}

// The point nearest to (x, y), in the capture's pixels; -1 when there is none.
export function nearest(points: Points, x: number, y: number): number {
  let best = -1
  let bestDistance = Infinity
  for (let i = 0; i < points.count; i++) {
    const dx = (points.xy[2 * i] ?? 0) - x
    const dy = (points.xy[2 * i + 1] ?? 0) - y
    const distance = dx * dx + dy * dy
    if (distance < bestDistance) {
      bestDistance = distance
      best = i
    }
  }
  return best
}

// The template as a picture: one line per group of points, one column per number, each value the group's
// mean, so that thousands of points fit the screen.
export function heatmapLines(points: Points, lines: number): { rows: number; values: Float32Array; height: number } {
  const rows = Math.max(1, Math.ceil(points.count / lines))
  const height = Math.ceil(points.count / rows)
  const values = new Float32Array(height * DESCRIPTOR_LENGTH)
  for (let line = 0; line < height; line++) {
    const first = line * rows
    const last = Math.min(points.count, first + rows)
    for (let column = 0; column < DESCRIPTOR_LENGTH; column++) {
      let sum = 0
      for (let row = first; row < last; row++) sum += points.descriptors[row * DESCRIPTOR_LENGTH + column] ?? 0
      values[line * DESCRIPTOR_LENGTH + column] = sum / (last - first)
    }
  }
  return { rows, values, height }
}

export type SealedPart = 'magic' | 'version' | 'salt' | 'nonce' | 'ciphertext' | 'tag'

// The first bytes of a sealed value and its tag, as hex, each marked with the part it belongs to (H14).
export function sealedBytes(layout: SealedLayout): Array<{ part: SealedPart; hex: string[]; total: number }> {
  const head = fromBase64(layout.head)
  const tag = fromBase64(layout.tag)
  const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  const bounds: Array<[SealedPart, number]> = [
    ['magic', layout.magic],
    ['version', layout.version],
    ['salt', layout.salt],
    ['nonce', layout.nonce],
  ]
  const parts: Array<{ part: SealedPart; hex: string[]; total: number }> = []
  let start = 0
  for (const [part, size] of bounds) {
    parts.push({ part, hex: hex(head.subarray(start, start + size)), total: size })
    start += size
  }
  parts.push({ part: 'ciphertext', hex: hex(head.subarray(start)), total: layout.ciphertext })
  parts.push({ part: 'tag', hex: hex(tag), total: layout.tag_bytes })
  return parts
}

export function megabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1)
}
