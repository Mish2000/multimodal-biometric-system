// H48: which camera the face screens use, decided without the user unless they choose.
//
// A camera is known by its model, the USB vendor and product that Chromium adds to its label on Windows
// ("Microsoft® LifeCam HD-3000 (045e:0779)"), so a choice survives another USB port. The built-in camera is
// the one facing the user: Windows' panel location, which Chromium reports as facingMode "user"; no name is
// relied on. With the laptop's lid closed the built-in screen is off, and the built-in camera, still listed,
// sends only a flat dark image; such a camera is tried last, and a flat image marks any camera as covered.

export interface Camera {
  deviceId: string
  name: string
  key: string // the model when the label has one, otherwise the label
  builtIn: boolean
}

export interface Situation {
  remembered: string | null // the camera the user chose last on this computer
  internalDisplay: boolean // the built-in screen is on: the lid is open
  covered: ReadonlySet<string> // cameras found covered since the cameras or the lid last changed
}

const MODEL = /\s*\(([0-9a-f]{4}:[0-9a-f]{4})\)\s*$/i

export function modelOf(label: string): string | null {
  const found = MODEL.exec(label)
  return found ? found[1]!.toLowerCase() : null
}

export function cameraFrom(device: { deviceId: string; label: string; facing: readonly string[] }): Camera {
  return {
    deviceId: device.deviceId,
    name: device.label.replace(MODEL, '').trim(),
    key: modelOf(device.label) ?? device.label,
    builtIn: device.facing.includes('user'),
  }
}

// The order in which cameras are tried: the remembered one, then cameras that are not built in, then the
// built-in one while its screen is on, and last the built-in one with its lid closed, whose frames decide.
export function ranked(cameras: readonly Camera[], situation: Situation): Camera[] {
  const rank = (camera: Camera) =>
    camera.builtIn && !situation.internalDisplay ? 3 : camera.key === situation.remembered ? 0 : camera.builtIn ? 2 : 1
  return cameras.filter((camera) => !situation.covered.has(camera.key)).sort((a, b) => rank(a) - rank(b))
}

export function choose(cameras: readonly Camera[], situation: Situation): Camera | null {
  return ranked(cameras, situation)[0] ?? null
}

// A covered lens sends a flat image. With its lid closed, the researcher's built-in camera gave a luma spread
// of 1.2 (mean 27); a room gave 51 to 72. A second of flat frames at the start is required, since a camera's
// first frames can be dark while its exposure settles.
export const FLAT_SPREAD = 5
export const FLAT_SAMPLES = 5

export function lumaSpread(rgba: ArrayLike<number>): number {
  let sum = 0
  let squares = 0
  const pixels = rgba.length / 4
  for (let i = 0; i < rgba.length; i += 4) {
    const luma = 0.299 * rgba[i]! + 0.587 * rgba[i + 1]! + 0.114 * rgba[i + 2]!
    sum += luma
    squares += luma * luma
  }
  const mean = sum / pixels
  return Math.sqrt(Math.max(0, squares / pixels - mean * mean))
}

export function looksCovered(spreads: readonly number[]): boolean {
  return spreads.length >= FLAT_SAMPLES && spreads.slice(0, FLAT_SAMPLES).every((spread) => spread < FLAT_SPREAD)
}

// What the live view asks of the user, from the faces found in a frame (in the frame's own pixels). The
// server checks the taken image again with the same rules.
export type Guidance = 'noFace' | 'several' | 'outside' | 'closer' | 'ready'

export function guidance(faces: ReadonlyArray<{ box: readonly number[] }>, width: number, height: number, minimumWidth: number): Guidance {
  if (faces.length === 0) return 'noFace'
  if (faces.length > 1) return 'several'
  const [x = 0, y = 0, w = 0, h = 0] = faces[0]!.box
  if (x < 0 || y < 0 || x + w > width || y + h > height) return 'outside'
  if (w < minimumWidth) return 'closer'
  return 'ready'
}

const STORED = 'mbs.camera'

export function rememberedCamera(): string | null {
  try {
    return window.localStorage.getItem(STORED)
  } catch {
    return null
  }
}

export function rememberCamera(key: string): void {
  try {
    window.localStorage.setItem(STORED, key)
  } catch {
    // the choice is then kept for this session only
  }
}
