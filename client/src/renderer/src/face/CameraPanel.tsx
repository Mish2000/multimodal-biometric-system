// H48: the camera of the face screens, chosen by the client: the live view of the current camera, a selector
// when more than one can be used, and what happened when a camera was covered, unplugged or refused.
// Enrolment (H48) and verification (H49) share it.
import { useState } from 'react'
import { useSession } from '../session'
import type { Camera } from './camera'
import { CameraView, type CameraProblem } from './CameraView'
import { useCameras } from './useCameras'

interface Props {
  busy: boolean
  minimumWidth: number
  onTaken(image: string, capturedAt: string): void
}

export function CameraPanel({ busy, minimumWidth, onTaken }: Props) {
  const { t } = useSession()
  const f = t.face
  const choice = useCameras()
  const [notice, setNotice] = useState('')
  const [problem, setProblem] = useState<{ camera: string; text: string } | null>(null)

  function lost(camera: Camera, text: string) {
    setNotice(text)
    setProblem(null)
    choice.markCovered(camera)
  }

  function refused(camera: Camera, kind: CameraProblem) {
    const text = kind === 'busy' ? f.cameraBusy : kind === 'denied' ? f.cameraDenied : f.cameraFailed
    setProblem({ camera: camera.key, text })
  }

  const current = choice.current
  const retry = () => {
    setNotice('')
    setProblem(null)
    choice.retry()
  }
  return (
    <>
      {choice.usable.length > 1 && current !== null && (
        <div className="camera-picker">
          <label>
            {f.camera}{' '}
            <select value={current.key} onChange={(event) => {
              const camera = choice.usable.find((item) => item.key === event.target.value)
              if (camera) {
                setNotice('')
                choice.pick(camera)
              }
            }}>
              {choice.usable.map((camera) => (
                <option key={camera.key} value={camera.key}>
                  {camera.name}{camera.builtIn ? ` (${f.builtIn})` : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {notice && <p className="notice" role="status">{notice}</p>}
      {choice.cameras === null ? (
        <p className="aside">{f.starting}</p>
      ) : current === null ? (
        <>
          <p className="error" role="alert">
            {choice.cameras.some((camera) => camera.builtIn) && !choice.cameras.some((camera) => !camera.builtIn) ? f.lidClosed : f.noCamera}
          </p>
          <button type="button" onClick={retry}>{f.retryCameras}</button>
        </>
      ) : problem !== null && problem.camera === current.key ? (
        <>
          <p className="error" role="alert">{problem.text}</p>
          <button type="button" onClick={retry}>{f.retryCameras}</button>
        </>
      ) : (
        <CameraView
          key={current.deviceId}
          camera={current}
          busy={busy}
          minimumWidth={minimumWidth}
          onTaken={onTaken}
          onCovered={() => lost(current, f.covered(current.name))}
          onEnded={() => lost(current, f.disconnected(current.name))}
          onProblem={(kind) => refused(current, kind)}
        />
      )}
    </>
  )
}
