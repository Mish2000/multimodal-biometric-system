// H22: where the finger lies in a capture, from the image alone, and how its print is drawn on a plate. The stage
// raises it as a relief; the flat plates of the other screens draw the same print in ink on the plate's surface, so a
// capture looks the same everywhere and the dark theme shows its negative (Light Table's sample plate).

export const MAP = 64 // the side of the low relief map

export interface Relief {
  /** The grey levels of ink and of the background, 0 to 1, for showing the ridges. */
  low: number
  high: number
  /** How far the finger rises at each cell of the map, 0 to 1. */
  dome: Float32Array
}

export const smooth = (low: number, high: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - low) / (high - low)))
  return t * t * (3 - 2 * t)
}

function blur(source: Float32Array, radius: number): Float32Array {
  let from = source
  for (const [dx, dy] of [[1, 0], [0, 1]] as const) {
    const to = new Float32Array(from.length)
    for (let y = 0; y < MAP; y += 1) {
      for (let x = 0; x < MAP; x += 1) {
        let sum = 0
        for (let k = -radius; k <= radius; k += 1) {
          const sx = Math.min(MAP - 1, Math.max(0, x + k * dx))
          const sy = Math.min(MAP - 1, Math.max(0, y + k * dy))
          sum += from[sy * MAP + sx]!
        }
        to[y * MAP + x] = sum / (radius * 2 + 1)
      }
    }
    from = to
  }
  return from
}

/** A capture sent as PNG in base64, decoded. */
export async function decodeCapture(base64: string): Promise<HTMLImageElement> {
  const image = new Image()
  image.src = `data:image/png;base64,${base64}`
  await image.decode()
  return image
}

/** The area whose ridges darken the capture, rounded into a dome, and the capture's own ink and paper levels. */
export function reliefOf(image: HTMLImageElement): Relief {
  const side = MAP * 4
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = side
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) throw new Error('no 2D canvas for the relief')
  context.drawImage(image, 0, 0, side, side)
  const pixels = context.getImageData(0, 0, side, side).data
  const histogram = new Uint32Array(256)
  for (let at = 0; at < pixels.length; at += 4) histogram[pixels[at]!] = histogram[pixels[at]!]! + 1
  const level = (share: number) => {
    let seen = 0
    for (let value = 0; value < 256; value += 1) {
      seen += histogram[value]!
      if (seen >= share * side * side) return value
    }
    return 255
  }
  const high = level(0.98)
  const low = Math.min(level(0.02), high - 16)
  const dark = new Float32Array(MAP * MAP)
  for (let y = 0; y < side; y += 1) {
    for (let x = 0; x < side; x += 1) {
      const ink = Math.min(1, Math.max(0, (high - pixels[(y * side + x) * 4]!) / (high - low)))
      dark[(y >> 2) * MAP + (x >> 2)] = dark[(y >> 2) * MAP + (x >> 2)]! + ink / 16
    }
  }
  const mask = blur(blur(dark, 2), 2).map((value) => smooth(0.1, 0.3, value))
  const round = blur(blur(mask, 6), 6)
  return { low: low / 255, high: high / 255, dome: mask.map((value, at) => value * smooth(0.25, 1, round[at]!)) }
}

/** The dome's height at a place of the capture, u and v from 0 to 1, between the map's cells. */
export function domeAt(relief: Relief, u: number, v: number): number {
  const x = Math.min(MAP - 1, Math.max(0, u * MAP - 0.5))
  const y = Math.min(MAP - 1, Math.max(0, v * MAP - 0.5))
  const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(MAP - 1, x0 + 1), y1 = Math.min(MAP - 1, y0 + 1)
  const top = relief.dome[y0 * MAP + x0]! + (relief.dome[y0 * MAP + x1]! - relief.dome[y0 * MAP + x0]!) * (x - x0)
  const bottom = relief.dome[y1 * MAP + x0]! + (relief.dome[y1 * MAP + x1]! - relief.dome[y1 * MAP + x0]!) * (x - x0)
  return top + (bottom - top) * (y - y0)
}

export interface PlateColors { surface: string; ink: string; mist: string }

/** The plate's colours of the current theme, from the page's tokens. */
export function plateColors(): PlateColors {
  const style = getComputedStyle(document.documentElement)
  const of = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return { surface: of('--surface', '#ffffff'), ink: of('--ink', '#171a4a'), mist: of('--mist', '#d5dbe8') }
}

const channels = (hex: string) => [1, 3, 5].map((at) => parseInt(hex.trim().slice(at, at + 2), 16))

/**
 * Draws a capture as the stage shows it from straight above before it tilts: the print in ink on the plate's
 * surface, the ridges by the capture's own levels and only where the finger lies, with the plate's rounded edge and
 * mist rim. `canvas` is sized to the plate in device pixels. Without an image the plate is drawn empty.
 */
export function paintPlate(canvas: HTMLCanvasElement, image: HTMLImageElement | null, relief: Relief | null, colors: PlateColors): void {
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return
  const side = canvas.width
  const surface = channels(colors.surface), ink = channels(colors.ink), mist = channels(colors.mist)
  const output = context.createImageData(side, side)
  let grey: Uint8ClampedArray | null = null
  if (image && relief) {
    const source = document.createElement('canvas')
    source.width = source.height = side
    const drawing = source.getContext('2d', { willReadFrequently: true })
    if (drawing) {
      drawing.drawImage(image, 0, 0, side, side)
      grey = drawing.getImageData(0, 0, side, side).data
    }
  }
  for (let y = 0; y < side; y += 1) {
    for (let x = 0; x < side; x += 1) {
      const u = (x + 0.5) / side, v = (y + 0.5) / side
      // The same rounded edge and rim as the stage's plate shader.
      const qx = Math.max(Math.abs(u - 0.5) * 2 - 0.93, 0), qy = Math.max(Math.abs(v - 0.5) * 2 - 0.93, 0)
      const edge = Math.hypot(qx, qy) - 0.07
      const soft = 2 / side
      const alpha = 1 - smooth(-soft, soft, edge)
      const at = (y * side + x) * 4
      if (alpha <= 0) continue
      let tone = 0
      if (grey && relief) {
        const finger = smooth(0.02, 0.25, domeAt(relief, u, v))
        const level = grey[at]! / 255
        tone = smooth(0.3, 0.7, Math.min(1, Math.max(0, (relief.high - level) / (relief.high - relief.low))) * finger) * 0.94
      }
      const rim = smooth(-0.014 - soft, -0.014 + soft, edge)
      for (let c = 0; c < 3; c += 1) {
        const base = surface[c]! + (ink[c]! - surface[c]!) * tone
        output.data[at + c] = base + (mist[c]! - base) * rim
      }
      output.data[at + 3] = Math.round(alpha * 255)
    }
  }
  context.putImageData(output, 0, 0)
}

/** A decoded capture with its relief, made once per capture while the page holds it. */
export interface DecodedCapture { image: HTMLImageElement; relief: Relief }

const decoded = new Map<string, Promise<DecodedCapture>>()

export function decodedCapture(base64: string): Promise<DecodedCapture> {
  let found = decoded.get(base64)
  if (!found) {
    found = decodeCapture(base64).then((image) => ({ image, relief: reliefOf(image) }))
    found.catch(() => decoded.delete(base64))
    decoded.set(base64, found)
    // A few screens' captures at most: the oldest goes first.
    if (decoded.size > 24) decoded.delete(decoded.keys().next().value!)
  }
  return found
}

/**
 * The capture drawn on its plate as a PNG data address, `side` pixels square, for drawings that place it as an image
 * (the flat match drawing of H43). Null where the page cannot draw.
 */
export async function plateImage(base64: string, side: number, colors: PlateColors): Promise<string | null> {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = side
  if (!canvas.getContext('2d', { willReadFrequently: true })) return null
  const { image, relief } = await decodedCapture(base64)
  paintPlate(canvas, image, relief, colors)
  return canvas.toDataURL('image/png')
}
