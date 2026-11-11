import { describe, expect, it } from 'vitest'
import { looksSilent, microphonesFrom, ranked, type DeviceEntry } from './microphone'
import { base64Of, envelope, levelOf, toPcm16, wavBytes } from './wav'

// The microphones of the researcher's PC as Chromium listed them on 2026-11-11 (the probe read no sound).
const DEVICES: DeviceEntry[] = [
  { kind: 'audioinput', deviceId: 'default', label: 'Default - Microphone (4- USB Audio Device) (1b3f:2008)', groupId: 'g-adapter' },
  { kind: 'audioinput', deviceId: 'communications', label: 'Communications - Microphone (4- USB Audio Device) (1b3f:2008)', groupId: 'g-adapter' },
  { kind: 'audioinput', deviceId: 'array', label: 'Microphone Array (Realtek(R) Audio)', groupId: 'g-array' },
  { kind: 'audioinput', deviceId: 'adapter', label: 'Microphone (4- USB Audio Device) (1b3f:2008)', groupId: 'g-adapter' },
  { kind: 'audioinput', deviceId: 'lifecam', label: 'Desktop Microphone (2- Microsoft® LifeCam HD-3000) (045e:0779)', groupId: 'g-lifecam' },
  { kind: 'videoinput', deviceId: 'cam1', label: 'Microsoft® LifeCam HD-3000 (045e:0779)', groupId: 'g-lifecam' },
  { kind: 'videoinput', deviceId: 'cam2', label: 'Integrated Camera (30c9:00f8)', groupId: 'g-integrated' },
  { kind: 'audiooutput', deviceId: 'out', label: 'Speakers (4- USB Audio Device) (1b3f:2008)', groupId: 'g-adapter' },
]

describe('the microphone choice (H54)', () => {
  const microphones = microphonesFrom(DEVICES)

  it('lists each microphone once, known by its model, and marks a camera’s own one and Windows’ default', () => {
    expect(microphones.map((m) => [m.key, m.name, m.usb, m.camera, m.windowsDefault])).toEqual([
      ['Microphone Array (Realtek(R) Audio)', 'Microphone Array (Realtek(R) Audio)', false, false, false],
      ['1b3f:2008', 'Microphone (USB Audio Device)', true, false, true],
      ['045e:0779', 'Desktop Microphone (Microsoft® LifeCam HD-3000)', true, true, false],
    ])
  })

  it('tries the camera’s own microphone first, then Windows’ default, then the others', () => {
    const order = ranked(microphones, { remembered: null, silent: new Set() })
    expect(order.map((m) => m.key)).toEqual(['045e:0779', '1b3f:2008', 'Microphone Array (Realtek(R) Audio)'])
  })

  it('tries the user’s last choice first, and passes over a silent microphone', () => {
    const remembered = ranked(microphones, { remembered: 'Microphone Array (Realtek(R) Audio)', silent: new Set() })
    expect(remembered[0]!.key).toBe('Microphone Array (Realtek(R) Audio)')
    const silent = ranked(microphones, { remembered: null, silent: new Set(['045e:0779']) })
    expect(silent.map((m) => m.key)).toEqual(['1b3f:2008', 'Microphone Array (Realtek(R) Audio)'])
  })

  it('without the camera (a meeting room), Windows’ default goes first', () => {
    const away = microphonesFrom(DEVICES.filter((d) => d.deviceId !== 'lifecam' && d.deviceId !== 'cam1').map((d) =>
      d.deviceId === 'default' ? { ...d, label: 'Default - Microphone Array (Realtek(R) Audio)', groupId: 'g-array' } : d))
    expect(ranked(away, { remembered: '045e:0779', silent: new Set() })[0]!.key).toBe('Microphone Array (Realtek(R) Audio)')
  })

  it('takes only exact digital silence, for a second and a half, as a silent microphone', () => {
    expect(looksSilent(0, 1.6)).toBe(true)
    expect(looksSilent(0, 1.0)).toBe(false)
    expect(looksSilent(1 / 32768, 2)).toBe(false)
  })
})

describe('the recording as the server takes it (H54)', () => {
  it('turns Web Audio’s samples into 16-bit PCM, clipped at the limits', () => {
    expect(Array.from(toPcm16(new Float32Array([0, 0.5, -0.5, 1, -1, 1.5, -2])))).toEqual([0, 16384, -16384, 32767, -32768, 32767, -32768])
  })

  it('writes a WAV of one channel and 16-bit PCM at the given rate', () => {
    const bytes = wavBytes(new Int16Array([1, -2, 300]), 16000)
    const view = new DataView(bytes.buffer)
    const text = (start: number, length: number) => String.fromCharCode(...bytes.subarray(start, start + length))
    expect([text(0, 4), text(8, 8), text(36, 4)]).toEqual(['RIFF', 'WAVEfmt ', 'data'])
    expect([view.getUint32(4, true), view.getUint16(20, true), view.getUint16(22, true), view.getUint32(24, true)]).toEqual([42, 1, 1, 16000])
    expect([view.getUint32(28, true), view.getUint16(32, true), view.getUint16(34, true), view.getUint32(40, true)]).toEqual([32000, 2, 16, 6])
    expect([view.getInt16(44, true), view.getInt16(46, true), view.getInt16(48, true)]).toEqual([1, -2, 300])
    expect(atob(base64Of(bytes)).length).toBe(50)
  })

  it('measures a block’s level and draws its envelope', () => {
    expect(levelOf(new Float32Array(160))).toBe(-100)
    expect(levelOf(new Float32Array(160).fill(0.1))).toBeCloseTo(-20, 5)
    expect(envelope(new Int16Array([0, 16384, -32768, 8192]), 2)).toEqual([[0, 0.5], [-1, 0.25]])
  })
})
