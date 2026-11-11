// H54: which microphone the voice screens use, decided without the user unless they choose.
//
// A microphone is known by its model, the USB vendor and product that Chromium adds to its label on Windows
// ("Desktop Microphone (2- Microsoft® LifeCam HD-3000) (045e:0779)"), so a choice survives another USB port and
// Windows' "2- " numbering; one without a model (the laptop's own) is known by its name. Chromium gives a camera
// and the microphone of the same device one group, so a camera's own microphone, the one that faces the user,
// can be told apart. On the researcher's PC (2026-11-11) Windows' default microphone was a USB audio adapter,
// while the LifeCam's microphone shared the LifeCam's group. The order is therefore the user's last choice, then
// a camera's own microphone, then Windows' default, then the others, USB ones first; a microphone that sends
// nothing but digital silence is passed over until the microphones change.
import { modelOf } from '../face/camera'

export interface Microphone {
  deviceId: string
  name: string // the label without Chromium's model and Windows' numbering
  key: string // the model when the label has one, otherwise the name
  usb: boolean
  camera: boolean // the microphone of a camera: the same device group
  windowsDefault: boolean
}

export interface MicrophoneSituation {
  remembered: string | null // the microphone the user chose last on this computer
  silent: ReadonlySet<string> // microphones found silent since the microphones last changed
}

export interface DeviceEntry {
  kind: string
  deviceId: string
  label: string
  groupId: string
}

const MODEL = /\s*\(([0-9a-f]{4}:[0-9a-f]{4})\)\s*$/i
const NUMBERING = /\(\d+- /g // Windows numbers devices of one name: "Microphone (2- USB Audio Device)"
const ALIASES = new Set(['default', 'communications']) // Chromium's entries for Windows' two default roles

export function microphonesFrom(devices: readonly DeviceEntry[]): Microphone[] {
  const cameraGroups = new Set(devices.filter((d) => d.kind === 'videoinput' && d.groupId !== '').map((d) => d.groupId))
  const inputs = devices.filter((d) => d.kind === 'audioinput')
  const fallback = inputs.find((d) => d.deviceId === 'default')
  const isDefault = (device: DeviceEntry) =>
    fallback !== undefined &&
    (fallback.label !== '' ? fallback.label.endsWith(` - ${device.label}`) : fallback.groupId !== '' && fallback.groupId === device.groupId)
  return inputs
    .filter((device) => !ALIASES.has(device.deviceId))
    .map((device) => {
      const model = modelOf(device.label)
      const name = device.label.replace(MODEL, '').replace(NUMBERING, '(').trim()
      return {
        deviceId: device.deviceId,
        name,
        key: model ?? name,
        usb: model !== null,
        camera: device.groupId !== '' && cameraGroups.has(device.groupId),
        windowsDefault: isDefault(device),
      }
    })
}

// The order in which microphones are tried.
export function ranked(microphones: readonly Microphone[], situation: MicrophoneSituation): Microphone[] {
  const rank = (m: Microphone) =>
    m.key === situation.remembered ? 0 : m.camera ? 1 : m.windowsDefault ? 2 : m.usb ? 3 : 4
  return microphones.filter((m) => !situation.silent.has(m.key)).sort((a, b) => rank(a) - rank(b))
}

// A microphone with nothing behind it sends exact zeros; a real one always hears some noise of the room. The
// first second and a half after it opens decides, since a device may start with a few silent blocks.
export const SILENT_SECONDS = 1.5

export function looksSilent(peak: number, seconds: number): boolean {
  return seconds >= SILENT_SECONDS && peak === 0
}

const STORED = 'mbs.microphone'

export function rememberedMicrophone(): string | null {
  try {
    return window.localStorage.getItem(STORED)
  } catch {
    return null
  }
}

export function rememberMicrophone(key: string): void {
  try {
    window.localStorage.setItem(STORED, key)
  } catch {
    // the choice is then kept for this session only
  }
}
