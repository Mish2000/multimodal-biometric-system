// H22: the stage of a fingerprint 1:1 result. The new capture and the stored one lie side by side as reliefs made
// from the images themselves, and a thread joins each pair the method counted (H43, H44). Everything drawn is the
// comparison's own data: the two native images and the counted pairs. The moment's times are in match-timeline.ts.
import {
  BufferGeometry, Color, DataTexture, DoubleSide, Float32BufferAttribute, GLSL3, InstancedBufferAttribute, InstancedBufferGeometry,
  LinearFilter, LinearMipmapLinearFilter, Matrix4, Mesh, PerspectiveCamera, RawShaderMaterial, RedFormat, Scene, Texture,
  UnsignedByteType, Vector2, Vector3, WebGLRenderer, type IUniform,
} from 'three'
import { COUNT_MS, SKIP_MS, THREAD_MS, TILT_MS, countAt, easeInOut, timeline, type Timeline } from './match-timeline'
import { MAP, domeAt, reliefOf, type Relief } from './relief'

export { decodeCapture } from './relief'

const IMAGE = 1000 // the native side of a capture, in pixels (H7)
const PLATE_X = 1.14 // each plate's centre, to the left and to the right
const DOME = 0.11 // the finger's rise above its plate
const RIDGE = 0.034 // the ridges' depth, in the shading only
const GRID = 128 // the plate's cells: enough for the dome, since the ridges need no geometry
const SEGMENTS = 28 // of one thread
const FULL = 142 // the pairs for which the threads' weight was tuned

export interface StageColors { canvas: string; surface: string; ink: string; mist: string; mark: string }
/** What the page shows around the stage: the verdict's words, and the end of the moment. */
export interface StageState { verdict: boolean; done: boolean }
export interface StageOptions {
  reduced: boolean
  /** The captures start as reliefs, as on a result after an earlier one on the same screen. */
  tilted: boolean
  onChange: (state: StageState) => void
  /** The landed threads, called in the frame that draws them. */
  onCount: (count: number) => void
}
export interface StageInput {
  /** The new capture and the stored one, decoded. */
  fresh: HTMLImageElement
  stored: HTMLImageElement
  /** Probe x, y and reference x, y of each counted pair, in native pixels. */
  pairs: Float32Array
  threshold: number
}

let supported: boolean | null = null
/** Whether this page can draw the stage; without WebGL 2 the result is drawn flat instead. */
export function stageSupported(): boolean {
  if (supported === null) {
    supported = false
    if (typeof WebGL2RenderingContext !== 'undefined') {
      try {
        supported = document.createElement('canvas').getContext('webgl2') !== null
      } catch {
        supported = false
      }
    }
  }
  return supported
}

const rgb = (hex: string) => new Vector3(...[1, 3, 5].map((at) => parseInt(hex.trim().slice(at, at + 2), 16) / 255) as [number, number, number])
const PLATE_VERTEX = `
precision highp float;
in vec2 aUv;
uniform mat4 uCamera; uniform float uSide, uRelief; uniform sampler2D uDome;
out vec2 vUv;
void main() {
  vUv = aUv;
  float height = texture(uDome, aUv).r * ${DOME} * uRelief;
  gl_Position = uCamera * vec4(uSide * ${PLATE_X} + aUv.x * 2.0 - 1.0, height, aUv.y * 2.0 - 1.0, 1.0);
}`

const PLATE_FRAGMENT = `
precision highp float;
in vec2 vUv;
uniform sampler2D uPrint, uDome; uniform float uRelief; uniform vec2 uLevels; uniform vec3 uSurface, uInk, uMist;
out vec4 color;
float finger(vec2 uv) { return smoothstep(0.02, 0.25, texture(uDome, uv).r); }
float inkOf(vec2 uv) { return clamp((uLevels.y - texture(uPrint, uv).r) / (uLevels.y - uLevels.x), 0.0, 1.0) * finger(uv); }
float height(vec2 uv) { return texture(uDome, uv).r * ${DOME} + inkOf(uv) * ${RIDGE}; }
void main() {
  vec2 q = abs(vUv - 0.5) * 2.0;
  float edge = length(max(q - 0.93, 0.0)) - 0.07;
  float soft = fwidth(edge);
  float alpha = 1.0 - smoothstep(-soft, soft, edge);
  if (alpha <= 0.0) discard;
  float e = 1.5 / ${IMAGE}.0;
  float dx = (height(vUv + vec2(e, 0.0)) - height(vUv - vec2(e, 0.0))) / (4.0 * e);
  float dz = (height(vUv + vec2(0.0, e)) - height(vUv - vec2(0.0, e))) / (4.0 * e);
  vec3 n = normalize(vec3(-dx * uRelief, 1.0, -dz * uRelief));
  vec3 light = normalize(vec3(-0.5, 0.8, 0.35));
  float shade = clamp(dot(n, light) / light.y, 0.45, 1.45);
  vec3 base = mix(uSurface, uInk, smoothstep(0.3, 0.7, inkOf(vUv)) * 0.94);
  vec3 lit = base * min(shade, 1.0) + (vec3(1.0) - base) * max(shade - 1.0, 0.0) * 0.3;
  lit = mix(lit, uMist, smoothstep(-0.014 - soft, -0.014 + soft, edge));
  color = vec4(lit, alpha);
}`

const CURVE = `
vec3 curve(vec3 from, vec3 to, float index, float relief, float t) {
  from.y *= relief; to.y *= relief;
  vec3 middle = (from + to) * 0.5;
  middle.y += (0.2 + 0.24 * distance(from, to) + 0.14 * fract(index * 0.618)) * mix(0.25, 1.0, relief);
  float u = 1.0 - t;
  return u * u * from + 2.0 * u * t * middle + t * t * to;
}`

// cubic-bezier(0.23, 1, 0.32, 1), solved for the curve's own parameter by Newton's steps.
const EASE = `
float easeOut(float x) {
  float t = x;
  for (int i = 0; i < 6; i++) {
    float u = 1.0 - t;
    float at = 3.0 * u * u * t * 0.23 + 3.0 * u * t * t * 0.32 + t * t * t;
    float slope = 3.0 * u * u * 0.23 + 6.0 * u * t * 0.09 + 3.0 * t * t * 0.68;
    t = clamp(t - (at - x) / max(slope, 0.001), 0.0, 1.0);
  }
  float u = 1.0 - t;
  return 3.0 * u * t * (u + t) + t * t * t;
}`

const THREAD_VERTEX = `
precision highp float;
in vec2 aAlong; in vec3 aFrom; in vec3 aTo; in vec2 aOrder;
uniform mat4 uCamera; uniform vec2 uView; uniform float uTime, uRelief, uWidth, uSelected, uDim;
out float vAt, vDrawn, vSide, vChosen;
${CURVE}
${EASE}
void main() {
  float t = aAlong.x;
  vec4 here = uCamera * vec4(curve(aFrom, aTo, aOrder.y, uRelief, t), 1.0);
  vec4 before = uCamera * vec4(curve(aFrom, aTo, aOrder.y, uRelief, max(t - 0.02, 0.0)), 1.0);
  vec4 after = uCamera * vec4(curve(aFrom, aTo, aOrder.y, uRelief, min(t + 0.02, 1.0)), 1.0);
  vec2 along = normalize((after.xy / after.w - before.xy / before.w) * uView);
  vChosen = step(abs(aOrder.y - uSelected), 0.5);
  here.xy += vec2(-along.y, along.x) * aAlong.y * uWidth * (1.0 + vChosen * uDim) * 2.0 / uView * here.w;
  vAt = t; vSide = aAlong.y;
  vDrawn = easeOut(clamp((uTime - aOrder.x) / ${THREAD_MS}.0, 0.0, 1.0));
  gl_Position = here;
}`

const THREAD_FRAGMENT = `
precision highp float;
in float vAt, vDrawn, vSide, vChosen;
uniform vec3 uMark, uInk; uniform float uDim, uWeight;
out vec4 color;
void main() {
  if (vAt > vDrawn) discard;
  float alpha = uWeight * (1.0 - smoothstep(0.45, 1.0, abs(vSide)));
  // The bright head settles as the thread lands, instead of going out in one frame at its end.
  float head = (1.0 - smoothstep(0.0, 0.16, vDrawn - vAt)) * (1.0 - smoothstep(0.95, 1.0, vDrawn));
  alpha *= 1.0 + head;
  alpha = mix(alpha, mix(alpha * 0.22, 1.0 - smoothstep(0.6, 1.0, abs(vSide)), vChosen), uDim);
  color = vec4(mix(uMark, uInk, vChosen * uDim), min(alpha, 1.0));
}`

const POINT_VERTEX = `
precision highp float;
in vec2 aCorner; in vec4 aPoint; in float aIndex;
uniform mat4 uCamera; uniform vec2 uView; uniform float uTime, uRelief, uSize, uSelected, uDim;
out vec2 vCorner; out float vShown, vChosen;
${EASE}
void main() {
  vec4 here = uCamera * vec4(aPoint.x, aPoint.y * uRelief, aPoint.z, 1.0);
  vShown = easeOut(clamp((uTime - aPoint.w) / 90.0, 0.0, 1.0));
  vChosen = step(abs(aIndex - uSelected), 0.5);
  here.xy += aCorner * uSize * (0.55 + 0.45 * vShown) * (1.0 + 0.7 * vChosen * uDim) * 2.0 / uView * here.w;
  vCorner = aCorner;
  gl_Position = here;
}`

const POINT_FRAGMENT = `
precision highp float;
in vec2 vCorner; in float vShown, vChosen;
uniform vec3 uMark, uInk, uSurface; uniform float uDim, uPointWeight;
out vec4 color;
void main() {
  float d = length(vCorner);
  float alpha = (1.0 - smoothstep(0.82, 1.0, d)) * vShown;
  alpha *= mix(uPointWeight, mix(uPointWeight * 0.3, 1.0, vChosen), uDim);
  vec3 fill = mix(mix(uMark, uInk, vChosen * uDim), uSurface, (1.0 - smoothstep(0.34, 0.5, d)) * 0.9);
  color = vec4(fill, alpha);
}`

type Uniforms = Record<string, IUniform>

export class MatchStage {
  private readonly renderer: WebGLRenderer
  private readonly scene = new Scene()
  private readonly camera = new PerspectiveCamera(32, 1, 0.1, 40)
  private readonly matrix = new Matrix4()
  private readonly view = new Vector2(1, 1)
  private readonly shared: Uniforms
  private readonly plates: RawShaderMaterial[] = []
  private readonly disposables: Array<{ dispose(): void }> = []
  private readonly moment: Timeline
  private readonly ends: Array<[Vector3, Vector3]> = []
  private readonly observer: ResizeObserver
  private readonly pointSize: number
  private state: StageState = { verdict: false, done: false }
  private counted = -1
  private time = 0
  private rate = 1
  private running = false
  private selected = -1
  private frame = 0
  private timer = 0
  private before = 0
  private disposed = false

  constructor(
    private readonly canvas: HTMLCanvasElement,
    input: StageInput,
    colors: StageColors,
    private readonly options: StageOptions,
  ) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false })
    this.moment = timeline(input.pairs, input.threshold, options.tilted)
    const count = input.pairs.length / 4
    // A comparison of hundreds of pairs is drawn lighter, so that the prints stay readable under their marks.
    const dense = Math.sqrt(FULL / Math.max(count, 1))
    const weight = Math.min(1, Math.max(0.3, dense))
    this.pointSize = 4.6 * Math.min(1, Math.max(0.4, dense))
    this.shared = {
      uCamera: { value: this.matrix }, uView: { value: this.view }, uRelief: { value: 0 }, uTime: { value: 0 },
      uSelected: { value: -1 }, uDim: { value: 0 }, uWeight: { value: 0.42 * weight },
      uSurface: { value: new Vector3() }, uInk: { value: new Vector3() }, uMist: { value: new Vector3() }, uMark: { value: new Vector3() },
      uWidth: { value: 1.25 }, uSize: { value: 4.6 },
      uPointWeight: { value: Math.min(1, Math.max(0.4, dense * 1.3)) },
    }

    // The two plates: the new capture on the left, the stored one on the right, each in its own image frame (H43).
    const uvs = new Float32Array((GRID + 1) * (GRID + 1) * 2)
    for (let j = 0; j <= GRID; j += 1) for (let i = 0; i <= GRID; i += 1) uvs.set([i / GRID, j / GRID], (j * (GRID + 1) + i) * 2)
    const corners: number[] = []
    for (let j = 0; j < GRID; j += 1) {
      for (let i = 0; i < GRID; i += 1) {
        const a = j * (GRID + 1) + i, b = a + 1, c = a + GRID + 1, d = c + 1
        corners.push(a, c, b, b, c, d)
      }
    }
    const plate = this.keep(new BufferGeometry())
    plate.setAttribute('aUv', new Float32BufferAttribute(uvs, 2))
    plate.setIndex(corners)
    const reliefs = [input.fresh, input.stored].map((image, index) => {
      const relief = reliefOf(image)
      const print = this.keep(new Texture(image))
      print.flipY = false
      print.minFilter = LinearMipmapLinearFilter
      print.needsUpdate = true
      const dome = this.keep(new DataTexture(Uint8Array.from(relief.dome, (value) => Math.round(value * 255)), MAP, MAP, RedFormat, UnsignedByteType))
      dome.minFilter = dome.magFilter = LinearFilter
      dome.needsUpdate = true
      const material = this.material(PLATE_VERTEX, PLATE_FRAGMENT, {
        uSide: { value: index === 0 ? -1 : 1 }, uPrint: { value: print }, uDome: { value: dome }, uLevels: { value: new Vector2(relief.low, relief.high) },
      }, true)
      this.plates.push(material)
      this.add(plate, material, 0)
      return relief
    })

    // Each pair: the new capture's point, the stored capture's point, and the thread between them.
    const place = (x: number, y: number, side: number, relief: Relief) => {
      const u = x / IMAGE, v = y / IMAGE
      return new Vector3(side * PLATE_X + u * 2 - 1, domeAt(relief, u, v) * DOME + RIDGE * 0.5 + 0.012, v * 2 - 1)
    }
    const threads = new Float32Array(count * 8)
    const points = new Float32Array(count * 10)
    for (let index = 0; index < count; index += 1) {
      const from = place(input.pairs[index * 4]!, input.pairs[index * 4 + 1]!, -1, reliefs[0]!)
      const to = place(input.pairs[index * 4 + 2]!, input.pairs[index * 4 + 3]!, 1, reliefs[1]!)
      const start = this.moment.starts[index]!
      this.ends.push([from, to])
      threads.set([from.x, from.y, from.z, to.x, to.y, to.z, start, index], index * 8)
      points.set([from.x, from.y, from.z, start, index, to.x, to.y, to.z, start + COUNT_MS, index], index * 10)
    }
    const strip = new Float32Array((SEGMENTS + 1) * 4)
    const stripIndex: number[] = []
    for (let k = 0; k <= SEGMENTS; k += 1) {
      strip.set([k / SEGMENTS, -1, k / SEGMENTS, 1], k * 4)
      if (k < SEGMENTS) stripIndex.push(k * 2, k * 2 + 1, k * 2 + 2, k * 2 + 2, k * 2 + 1, k * 2 + 3)
    }
    const thread = this.keep(new InstancedBufferGeometry())
    thread.setAttribute('aAlong', new Float32BufferAttribute(strip, 2))
    thread.setIndex(stripIndex)
    const threadData = (offset: number, size: number) => {
      const values = new Float32Array(count * size)
      for (let index = 0; index < count; index += 1) values.set(threads.subarray(index * 8 + offset, index * 8 + offset + size), index * size)
      return new InstancedBufferAttribute(values, size)
    }
    thread.setAttribute('aFrom', threadData(0, 3))
    thread.setAttribute('aTo', threadData(3, 3))
    thread.setAttribute('aOrder', threadData(6, 2))
    thread.instanceCount = count
    const point = this.keep(new InstancedBufferGeometry())
    point.setAttribute('aCorner', new Float32BufferAttribute([-1, -1, 1, -1, -1, 1, 1, 1], 2))
    point.setIndex([0, 1, 2, 2, 1, 3])
    const pointData = (offset: number, size: number) => {
      const values = new Float32Array(count * 2 * size)
      for (let index = 0; index < count * 2; index += 1) values.set(points.subarray(index * 5 + offset, index * 5 + offset + size), index * size)
      return new InstancedBufferAttribute(values, size)
    }
    point.setAttribute('aPoint', pointData(0, 4))
    point.setAttribute('aIndex', pointData(4, 1))
    point.instanceCount = count * 2
    if (count > 0) {
      this.add(thread, this.material(THREAD_VERTEX, THREAD_FRAGMENT, {}, false), 1)
      this.add(point, this.material(POINT_VERTEX, POINT_FRAGMENT, {}, false), 2)
    }

    this.setColors(colors)
    this.observer = new ResizeObserver(() => this.invalidate())
    this.observer.observe(canvas)
    // The first frame is drawn at once, for the page to fade in: the two captures, or with reduced motion the
    // finished result.
    this.time = options.reduced ? this.moment.total : 0
    this.paint(performance.now(), true)
  }

  private keep<T extends { dispose(): void }>(item: T): T {
    this.disposables.push(item)
    return item
  }

  private material(vertexShader: string, fragmentShader: string, own: Uniforms, opaque: boolean): RawShaderMaterial {
    return this.keep(new RawShaderMaterial({
      glslVersion: GLSL3, vertexShader, fragmentShader, uniforms: { ...this.shared, ...own }, transparent: true, depthWrite: opaque, side: DoubleSide,
    }))
  }

  private add(geometry: BufferGeometry, material: RawShaderMaterial, order: number): void {
    const mesh = new Mesh(geometry, material)
    mesh.frustumCulled = false
    mesh.renderOrder = order
    this.scene.add(mesh)
  }

  /** The theme's colours, as the page has them now. */
  setColors(colors: StageColors): void {
    this.renderer.setClearColor(new Color(colors.canvas.trim()), 1)
    for (const [uniform, colour] of [['uSurface', colors.surface], ['uInk', colors.ink], ['uMist', colors.mist], ['uMark', colors.mark]] as const) {
      (this.shared[uniform]!.value as Vector3).copy(rgb(colour))
    }
    this.invalidate()
  }

  /** Plays the moment once, from its start. With reduced motion the result is already drawn, so nothing moves. */
  play(): void {
    if (this.options.reduced || this.running || this.time > 0) return
    this.running = true
    this.before = 0
    this.invalidate()
  }

  /** A press never has to wait: whatever is left plays out at once, as motion and not as a cut. */
  finish(): boolean {
    if (!this.running) return false
    this.rate = Math.max(this.rate, (this.moment.total - this.time) / SKIP_MS)
    return true
  }

  /** Holds the moment at one share of its time, for looking at a single frame. */
  seek(share: number): void {
    this.running = false
    this.time = share * this.moment.total
    this.invalidate()
  }

  /** The pair to draw as chosen, or -1 for none. The others dim gradually for the pointer and at once for a key. */
  select(index: number, instant = false): void {
    if (index === this.selected) return
    this.selected = index
    if (index >= 0) this.shared.uSelected!.value = index
    if (instant) this.shared.uDim!.value = index >= 0 ? 1 : 0
    this.invalidate()
  }

  /** The pair whose point is nearest to a place on the canvas, in its own CSS pixels, or -1. */
  pick(x: number, y: number): number {
    const m = this.matrix.elements
    const width = this.canvas.clientWidth, height = this.canvas.clientHeight
    let found = -1, best = 30 ** 2
    this.ends.forEach((pair, index) => {
      for (const p of pair) {
        const w = m[3]! * p.x + m[7]! * p.y + m[11]! * p.z + m[15]!
        const sx = ((m[0]! * p.x + m[4]! * p.y + m[8]! * p.z + m[12]!) / w * 0.5 + 0.5) * width
        const sy = (0.5 - (m[1]! * p.x + m[5]! * p.y + m[9]! * p.z + m[13]!) / w * 0.5) * height
        const distance = (sx - x) ** 2 + (sy - y) ** 2
        if (distance < best) {
          best = distance
          found = index
        }
      }
    })
    return found
  }

  dispose(): void {
    this.disposed = true
    cancelAnimationFrame(this.frame)
    window.clearTimeout(this.timer)
    this.observer.disconnect()
    for (const item of this.disposables) item.dispose()
    this.renderer.dispose()
  }

  // The count goes to the page in the frame that draws its threads; the verdict and the end change the page once.
  private report(count: number, verdict: boolean, done: boolean): void {
    if (count !== this.counted) {
      this.counted = count
      this.options.onCount(count)
    }
    if (verdict === this.state.verdict && done === this.state.done) return
    this.state = { verdict, done }
    this.options.onChange(this.state)
  }

  // A hidden window gets no animation frames; a slow timer still carries the moment to its end, so the result is
  // there when the window is seen again.
  private invalidate(): void {
    if (this.disposed) return
    this.frame ||= requestAnimationFrame((now) => this.paint(now, false))
    this.timer ||= window.setTimeout(() => this.paint(performance.now(), true), 120)
  }

  private paint(now: number, _byTimer: boolean): void {
    cancelAnimationFrame(this.frame)
    window.clearTimeout(this.timer)
    this.frame = this.timer = 0
    if (this.disposed) return
    const step = this.before ? Math.min(now - this.before, 250) : 0
    this.before = now
    const total = this.moment.total
    if (this.running) {
      this.time = Math.min(total, this.time + step * this.rate)
      if (this.time >= total) this.running = false
    }
    // The chosen thread changes at once; the others dim and return over about 150 ms, whatever the frame rate.
    const want = this.selected >= 0 ? 1 : 0
    const dim = this.shared.uDim!
    dim.value += (want - dim.value) * (1 - Math.exp(-step / 45))
    if (Math.abs(want - dim.value) < 0.01) dim.value = want
    this.draw(this.options.reduced || this.options.tilted ? 1 : easeInOut(this.time / TILT_MS))
    this.report(countAt(this.moment, this.time), this.time >= this.moment.verdictAt, this.time >= total)
    if (this.running || dim.value !== want) this.invalidate()
    else this.before = 0
  }

  private draw(tilt: number): void {
    const ratio = Math.min(window.devicePixelRatio, 2)
    const width = Math.max(1, this.canvas.clientWidth), height = Math.max(1, this.canvas.clientHeight)
    this.renderer.setPixelRatio(ratio)
    this.renderer.setSize(width, height, false)
    this.view.set(width * ratio, height * ratio)
    // From straight above, where the captures are two flat images, down to a view across their reliefs.
    const half = Math.tan((this.camera.fov * Math.PI) / 360)
    const aspect = width / height
    const distance = Math.max(2.42 / (half * aspect), 1.3 / half) * (1 - 0.14 * tilt)
    const pitch = ((89.4 - 39 * tilt) * Math.PI) / 180
    const yaw = -0.1 * tilt
    const target = new Vector3(0, 0.06 * tilt, 0.12 * tilt)
    this.camera.aspect = aspect
    this.camera.position.set(
      target.x + distance * Math.sin(yaw) * Math.cos(pitch), target.y + distance * Math.sin(pitch), target.z + distance * Math.cos(yaw) * Math.cos(pitch))
    this.camera.lookAt(target)
    this.camera.updateProjectionMatrix()
    this.camera.updateMatrixWorld()
    this.matrix.multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse)
    this.shared.uRelief!.value = tilt
    this.shared.uTime!.value = this.time
    this.shared.uWidth!.value = 1.25 * ratio
    this.shared.uSize!.value = this.pointSize * ratio
    this.renderer.render(this.scene, this.camera)
  }
}
