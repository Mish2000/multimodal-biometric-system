// H48: the cameras of this computer, as the face screens see them, kept up to date as cameras are plugged in
// or out (the browser's devicechange) and as the laptop's lid opens or closes (the main process's displays).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { cameraFrom, ranked, rememberCamera, rememberedCamera, type Camera } from './camera'

interface Facing {
  getCapabilities?: () => { facingMode?: string[] }
}

async function listCameras(): Promise<Camera[]> {
  const devices = await navigator.mediaDevices.enumerateDevices()
  return devices
    .filter((device) => device.kind === 'videoinput')
    .map((device) =>
      cameraFrom({
        deviceId: device.deviceId,
        label: device.label,
        facing: (device as unknown as Facing).getCapabilities?.().facingMode ?? [],
      }),
    )
}

// Names and panels stay hidden until the page has used a camera once; one short request reveals them.
async function readableCameras(): Promise<Camera[]> {
  const cameras = await listCameras()
  if (cameras.length === 0 || cameras.some((camera) => camera.name !== '')) return cameras
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
    stream.getTracks().forEach((track) => track.stop())
  } catch {
    // the camera's own opening reports the reason
  }
  return listCameras()
}

export interface Cameras {
  cameras: Camera[] | null // null while they are being looked for
  usable: Camera[] // in the order they are tried
  current: Camera | null
  internalDisplay: boolean
  markCovered(camera: Camera): void
  pick(camera: Camera): void
  retry(): void
}

export function useCameras(): Cameras {
  const [cameras, setCameras] = useState<Camera[] | null>(null)
  const [internalDisplay, setInternalDisplay] = useState(true)
  const [covered, setCovered] = useState<ReadonlySet<string>>(new Set())
  const [remembered, setRemembered] = useState<string | null>(rememberedCamera)
  const [picked, setPicked] = useState<string | null>(null) // chosen in this screen: tried first
  const [search, setSearch] = useState(0)

  useEffect(() => {
    let active = true
    const load = () => {
      readableCameras()
        .then((found) => {
          if (!active) return
          setCameras(found)
          setCovered(new Set()) // a camera came or went: every camera may be tried again
        })
        .catch(() => {
          if (active) setCameras([])
        })
    }
    load()
    navigator.mediaDevices.addEventListener('devicechange', load)
    return () => {
      active = false
      navigator.mediaDevices.removeEventListener('devicechange', load)
    }
  }, [search])

  useEffect(() => {
    let active = true
    void window.mbs.displays().then((state) => {
      if (active && state) setInternalDisplay(state.internalDisplay)
    })
    const stop = window.mbs.onDisplays((state) => {
      setInternalDisplay(state.internalDisplay)
      setCovered(new Set()) // the lid opened or closed
    })
    return () => {
      active = false
      stop()
    }
  }, [])

  const usable = useMemo(() => {
    if (cameras === null) return []
    const order = ranked(cameras, { remembered, internalDisplay, covered })
    const chosen = order.find((camera) => camera.key === picked)
    return chosen ? [chosen, ...order.filter((camera) => camera !== chosen)] : order
  }, [cameras, remembered, internalDisplay, covered, picked])

  const markCovered = useCallback((camera: Camera) => {
    setCovered((current) => new Set([...current, camera.key]))
  }, [])

  const pick = useCallback((camera: Camera) => {
    rememberCamera(camera.key)
    setRemembered(camera.key)
    setPicked(camera.key)
    setCovered((current) => new Set([...current].filter((key) => key !== camera.key)))
  }, [])

  const retry = useCallback(() => {
    setCovered(new Set())
    setSearch((count) => count + 1)
  }, [])

  return { cameras, usable, current: usable[0] ?? null, internalDisplay, markCovered, pick, retry }
}
