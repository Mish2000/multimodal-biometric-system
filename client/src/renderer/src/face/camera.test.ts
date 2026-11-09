import { describe, expect, it } from 'vitest'
import { cameraFrom, choose, guidance, looksCovered, lumaSpread, modelOf, ranked, type Camera, type Situation } from './camera'

const lifecam = cameraFrom({ deviceId: 'a', label: 'Microsoft® LifeCam HD-3000 (045e:0779)', facing: [] })
const builtIn = cameraFrom({ deviceId: 'b', label: 'Integrated Camera (30c9:00f8)', facing: ['user'] })
const situation = (extra: Partial<Situation> = {}): Situation => ({ remembered: null, internalDisplay: true, covered: new Set(), ...extra })

describe('the cameras of the face screens (H48)', () => {
  it('knows a camera by its model and the built-in one by the panel it faces from', () => {
    expect(modelOf('Microsoft® LifeCam HD-3000 (045e:0779)')).toBe('045e:0779')
    expect(modelOf('Some Camera')).toBeNull()
    expect(lifecam).toEqual({ deviceId: 'a', name: 'Microsoft® LifeCam HD-3000', key: '045e:0779', builtIn: false })
    expect(builtIn).toMatchObject({ name: 'Integrated Camera', key: '30c9:00f8', builtIn: true })
    expect(cameraFrom({ deviceId: 'c', label: 'Virtual', facing: [] }).key).toBe('Virtual')
  })

  it('in the researcher\'s room, with the lid closed, uses the USB camera', () => {
    expect(choose([builtIn, lifecam], situation({ internalDisplay: false }))).toBe(lifecam)
    // even when the built-in camera was the last choice
    expect(choose([builtIn, lifecam], situation({ internalDisplay: false, remembered: builtIn.key }))).toBe(lifecam)
  })

  it('at a meeting, with the lid open and no USB camera, uses the built-in one', () => {
    expect(choose([builtIn], situation())).toBe(builtIn)
  })

  it('with both available, takes the last choice, or else the USB camera', () => {
    expect(choose([builtIn, lifecam], situation())).toBe(lifecam)
    expect(choose([builtIn, lifecam], situation({ remembered: builtIn.key }))).toBe(builtIn)
    expect(choose([builtIn, lifecam], situation({ remembered: 'ffff:0001' }))).toBe(lifecam)
  })

  it('still tries the built-in camera when it is the only one, and skips a covered camera', () => {
    // When Windows reports no built-in screen, its frames decide, so it is not ruled out.
    expect(choose([builtIn], situation({ internalDisplay: false }))).toBe(builtIn)
    expect(choose([builtIn], situation({ internalDisplay: false, covered: new Set([builtIn.key]) }))).toBeNull()
    expect(ranked([builtIn, lifecam], situation({ covered: new Set([lifecam.key]) }))).toEqual([builtIn])
    expect(choose([] as Camera[], situation())).toBeNull()
  })

  it('finds a covered lens by a second of flat frames, as measured on the closed lid', () => {
    const flat = new Uint8ClampedArray(4 * 100).fill(27)
    expect(lumaSpread(flat)).toBeCloseTo(0, 6)
    const room = new Uint8ClampedArray(4 * 100).map((_, i) => (Math.floor(i / 4) % 2 ? 40 : 200))
    expect(lumaSpread(room)).toBeCloseTo(80, 6)
    expect(looksCovered([1.2, 1.4, 1.1, 1.3, 1.2])).toBe(true)
    expect(looksCovered([1.2, 1.4, 1.1, 1.3])).toBe(false) // not yet a second
    expect(looksCovered([1.2, 1.4, 55, 1.3, 1.2])).toBe(false)
  })

  it('guides the user with the same rules the server checks', () => {
    const face = (box: number[]) => ({ box })
    expect(guidance([], 1280, 720, 112)).toBe('noFace')
    expect(guidance([face([10, 10, 200, 240]), face([600, 10, 200, 240])], 1280, 720, 112)).toBe('several')
    expect(guidance([face([-4, 10, 200, 240])], 1280, 720, 112)).toBe('outside')
    expect(guidance([face([1100, 10, 200, 240])], 1280, 720, 112)).toBe('outside')
    expect(guidance([face([500, 200, 100, 120])], 1280, 720, 112)).toBe('closer')
    expect(guidance([face([500, 200, 223, 260])], 1280, 720, 112)).toBe('ready')
  })
})
