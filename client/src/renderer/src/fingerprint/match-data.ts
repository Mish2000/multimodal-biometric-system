// H43: native 1000-pixel image coordinates, held only for the current verification result.
import { fromBase64 } from './data'

export function decodeMatchPairs(encoded: string, count: number): Float32Array | null {
  if (!Number.isSafeInteger(count) || count < 0) return null
  try {
    const bytes = fromBase64(encoded)
    if (bytes.length !== count * 16) return null
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const pairs = new Float32Array(count * 4)
    for (let index = 0; index < pairs.length; index++) {
      const coordinate = data.getFloat32(index * 4, true)
      if (!Number.isFinite(coordinate) || coordinate < 0 || coordinate >= 1000) return null
      pairs[index] = coordinate
    }
    return pairs
  } catch {
    return null
  }
}

export function nearestMatch(pairs: Float32Array, x: number, y: number, reference: boolean): number {
  let selected = -1
  let distance = Infinity
  const offset = reference ? 2 : 0
  for (let index = 0; index < pairs.length / 4; index++) {
    const dx = pairs[index * 4 + offset]! - x
    const dy = pairs[index * 4 + offset + 1]! - y
    const current = dx * dx + dy * dy
    if (current < distance) {
      selected = index
      distance = current
    }
  }
  return selected
}
