// H48: one camera's live view. The picture is mirrored, as people expect of a camera that faces them; a small
// copy of a frame goes to the server about five times a second, and the face it finds is drawn over the view.
// The image the user takes is the camera's own frame, unmirrored, as a PNG. Nothing is stored here.
import { useEffect, useRef, useState } from 'react'
import type { FaceBox, FaceDetection } from '../../../shared/bridge'
import { useSession } from '../session'
import { FLAT_SAMPLES, guidance, looksCovered, lumaSpread, type Camera, type Guidance } from './camera'

const LIVE_WIDTH = 320 // the small copy sent to find the face; YuNet finds faces of a few pixels
const LIVE_PAUSE_MS = 150
const VIDEO = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }

export type CameraProblem = 'busy' | 'denied' | 'failed'

interface Props {
  camera: Camera
  busy: boolean // the page is waiting for the server, so no image is taken
  minimumWidth: number
  onTaken(image: string, capturedAt: string): void
  onCovered(): void
  onEnded(): void
  onProblem(problem: CameraProblem): void
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function problemOf(error: unknown): CameraProblem {
  const name = (error as { name?: string } | null)?.name
  if (name === 'NotReadableError' || name === 'AbortError') return 'busy'
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied'
  return 'failed'
}

export function CameraView({ camera, busy, minimumWidth, onTaken, onCovered, onEnded, onProblem }: Props) {
  const { call, t } = useSession()
  const f = t.face
  const video = useRef<HTMLVideoElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const [started, setStarted] = useState(false)
  const [faces, setFaces] = useState<FaceBox[]>([])
  const [live, setLive] = useState<Guidance | 'unavailable' | null>(null)
  const handlers = useRef({ onCovered, onEnded, onProblem })
  handlers.current = { onCovered, onEnded, onProblem }

  // The camera: opened for this view, stopped when the view goes or another camera is chosen.
  useEffect(() => {
    let active = true
    let stream: MediaStream | null = null
    setStarted(false)
    setFaces([])
    setLive(null)
    navigator.mediaDevices
      .getUserMedia({ video: { deviceId: { exact: camera.deviceId }, ...VIDEO }, audio: false })
      .then(async (opened) => {
        if (!active) {
          opened.getTracks().forEach((track) => track.stop())
          return
        }
        stream = opened
        const track = opened.getVideoTracks()[0]
        track?.addEventListener('ended', () => {
          if (active) handlers.current.onEnded()
        })
        const element = video.current
        if (element === null) return
        element.srcObject = opened
        await element.play().catch(() => undefined)
        if (active) setStarted(true)
      })
      .catch((error: unknown) => {
        if (active) handlers.current.onProblem(problemOf(error))
      })
    return () => {
      active = false
      stream?.getTracks().forEach((track) => track.stop())
      if (video.current) video.current.srcObject = null
    }
  }, [camera.deviceId])

  // The live loop: a small frame to the server, one at a time; its first frames also show a covered lens.
  useEffect(() => {
    if (!started) return
    let active = true
    const small = document.createElement('canvas')
    const context = small.getContext('2d', { willReadFrequently: true })
    const spreads: number[] = []
    void (async () => {
      while (active) {
        const element = video.current
        if (context === null || element === null || element.videoWidth === 0) {
          await pause(LIVE_PAUSE_MS)
          continue
        }
        small.width = LIVE_WIDTH
        small.height = Math.round((LIVE_WIDTH * element.videoHeight) / element.videoWidth)
        context.drawImage(element, 0, 0, small.width, small.height)
        if (spreads.length < FLAT_SAMPLES) {
          spreads.push(lumaSpread(context.getImageData(0, 0, small.width, small.height).data))
          if (looksCovered(spreads)) {
            handlers.current.onCovered()
            return
          }
        }
        const image = small.toDataURL('image/jpeg', 0.8).split(',')[1] ?? ''
        const answer = await call<FaceDetection>('detectFace', { image })
        if (!active) return
        if (answer.ok) {
          const scale = element.videoWidth / answer.data.width
          const found = answer.data.faces.map((face) => ({
            ...face,
            box: face.box.map((value) => value * scale) as FaceBox['box'],
            landmarks: face.landmarks.map(([x, y]) => [x * scale, y * scale] as [number, number]),
          }))
          setFaces(found)
          setLive(guidance(found, element.videoWidth, element.videoHeight, minimumWidth))
        } else {
          setFaces([])
          setLive('unavailable')
        }
        await pause(LIVE_PAUSE_MS)
      }
    })()
    return () => {
      active = false
    }
  }, [started, call, minimumWidth])

  // The found face, drawn in the frame's own pixels; the overlay is mirrored with the picture.
  useEffect(() => {
    const canvas = overlay.current
    const element = video.current
    const context = canvas?.getContext('2d')
    if (!canvas || !element || !context || element.videoWidth === 0) return
    canvas.width = element.videoWidth
    canvas.height = element.videoHeight
    context.clearRect(0, 0, canvas.width, canvas.height)
    const style = getComputedStyle(canvas)
    context.lineWidth = Math.max(2, canvas.width / 320)
    for (const face of faces) {
      context.strokeStyle =
        live === 'ready' ? style.getPropertyValue('--ok').trim() || '#1a7f37' : style.getPropertyValue('--medium').trim() || '#a16207'
      context.fillStyle = context.strokeStyle
      const [x, y, w, h] = face.box
      context.strokeRect(x, y, w, h)
      for (const [px, py] of face.landmarks) {
        context.beginPath()
        context.arc(px, py, context.lineWidth * 1.5, 0, 2 * Math.PI)
        context.fill()
      }
    }
  }, [faces, live])

  function take() {
    const element = video.current
    if (element === null || element.videoWidth === 0) return
    const frame = document.createElement('canvas')
    frame.width = element.videoWidth
    frame.height = element.videoHeight
    frame.getContext('2d')?.drawImage(element, 0, 0)
    onTaken(frame.toDataURL('image/png').split(',')[1] ?? '', new Date().toISOString())
  }

  const ready = live === 'ready' && !busy
  return (
    <div className="camera">
      <div className="camera-view">
        <video ref={video} muted playsInline aria-label={f.camera} />
        <canvas ref={overlay} aria-hidden="true" />
        {!started && <p className="camera-status">{f.starting}</p>}
      </div>
      <p className={live === 'ready' ? 'ok guidance' : 'notice guidance'} role="status" aria-live="polite">
        {live === null ? f.starting : f.guide[live] ?? ''}
      </p>
      <div className="actions">
        <button type="button" disabled={!ready} onClick={take}>
          {f.take}
        </button>
      </div>
    </div>
  )
}
