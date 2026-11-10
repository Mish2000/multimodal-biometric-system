// H49, H50: the pieces that face verification and identification share. Before an enrolment, the message of H15.
// H53: SFace's card is a choice between the camera and an existing image file (H27, H51), each on a screen of its
// own; the camera still starts only on that explicit choice (H40). Every attempt ends on an outcome screen (a
// result, a refused image with its checks, or a failure) whose "again" returns to the choice; a run takes one
// image. The page checks only a file's size; it sends the file's content alone, never its name, and the server
// decides by the content.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import type { FaceCheck, FaceDetection, FaceMethod, FaceSize, FaceSource, RouteName } from '../../../shared/bridge'
import { errorText } from '../texts'
import { useSession } from '../session'
import { CameraPanel } from './CameraPanel'
import { checkLine } from './FaceEnrolment'

export function FaceNotEnrolled({ title, text, onEnrol }: { title: ReactNode; text: string; onEnrol: () => void }) {
  const { t } = useSession()
  const navigate = useNavigate()
  return (
    <section>
      <h1>{title}</h1>
      <p className="notice" role="status">{text}</p>
      <div className="actions">
        <button type="button" onClick={onEnrol}>{t.face.verify.enrolNow}</button>
        <button type="button" className="secondary" onClick={() => navigate('/')}>{t.face.verify.home}</button>
      </div>
    </section>
  )
}

export function FaceChoice({ title, lead, method, notes, live, onLive, onFile, onLeave }: {
  title: ReactNode
  lead: string
  method: FaceMethod
  notes: string[]
  live: string
  onLive: () => void
  onFile: () => void
  onLeave: () => void
}) {
  const { t } = useSession()
  const f = t.face
  return (
    <section className="method-selection">
      <h1>{title}</h1>
      <p className="lead">{lead}</p>
      <div className="setting method-card">
        <h2>SFace</h2>
        <p>{f.methodText}</p>
        <p className="aside">{f.methodThreshold(method.threshold)}</p>
        <p className="aside">{f.methodAccuracy}</p>
        {notes.map((note) => <p key={note} className="aside">{note}</p>)}
      </div>
      <div className="actions">
        <button type="button" disabled={!method.available} onClick={onLive}>{live}</button>
        <button type="button" className="secondary" disabled={!method.available} onClick={onFile}>{f.files.upload}</button>
        <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
      </div>
      <p className="aside">{f.files.uploadNote}</p>
    </section>
  )
}

export const FILE_BYTES = 10 * 1024 * 1024 // H27

export function SourceLine({ source, size }: { source: FaceSource; size: FaceSize }) {
  const { t } = useSession()
  const files = t.face.files
  return (
    <p className="aside">
      {source === 'file' ? files.fromFile(size.decoded[0], size.decoded[1], size.stored[0], size.stored[1]) : files.fromCamera}
    </p>
  )
}

function base64Of(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes('Files')

type Rejected = { status: 'rejected'; checks: FaceCheck[] } & FaceDetection

export function FaceTake<T extends { status: string }>({ title, mode, route, minimumWidth, comparing, errors, again, onResult, onChoice, onLeave }: {
  title: ReactNode
  mode: 'live' | 'file'
  route: Extract<RouteName, 'verifyFace' | 'identifyFace'>
  minimumWidth: number
  comparing: string
  errors?: Record<string, string>
  again: string
  onResult: (result: T) => void
  onChoice: () => void
  onLeave: () => void
}) {
  const { call, t } = useSession()
  const f = t.face
  const [phase, setPhase] = useState<'ready' | 'checking' | 'rejected' | 'failed'>('ready')
  const [rejected, setRejected] = useState<FaceCheck[]>([])
  const [failure, setFailure] = useState('')
  const [notice, setNotice] = useState('') // a file the page itself could not use (H51)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const latestFile = useRef<(files: File[]) => void>(() => undefined)

  async function check(image: string, source: FaceSource) {
    setNotice('')
    setPhase('checking')
    const answer = await call<T | Rejected>(route, { image, source })
    if (!answer.ok) {
      setFailure(errors?.[answer.error] ?? f.errors[answer.error] ?? errorText(answer, t))
      setPhase('failed')
      return
    }
    if (answer.data.status !== 'rejected') {
      onResult(answer.data as T)
      return
    }
    setRejected((answer.data as Rejected).checks)
    setPhase('rejected')
  }

  async function takeFile(files: File[]) {
    setNotice('')
    const [file] = files
    if (phase !== 'ready' || file === undefined) return
    if (files.length > 1) return setNotice(f.files.oneFile)
    if (file.size > FILE_BYTES) return setNotice(f.files.tooLarge)
    let image: string
    try {
      image = await base64Of(file)
    } catch {
      return setNotice(f.files.unreadable)
    }
    await check(image, 'file')
  }
  latestFile.current = (files) => void takeFile(files)

  // H51, H53: on the file screen, a file dragged over the window marks the drop zone and is taken when dropped;
  // the browser's own handling (opening the file in the window) is prevented. The camera screen takes no file.
  useEffect(() => {
    if (mode !== 'file') return
    let depth = 0
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      depth += 1
      setDragging(true)
    }
    const over = (event: DragEvent) => {
      if (carriesFiles(event)) event.preventDefault()
    }
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setDragging(false)
    }
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      depth = 0
      setDragging(false)
      latestFile.current(Array.from(event.dataTransfer?.files ?? []))
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [mode])

  if (phase === 'rejected' || phase === 'failed')
    return (
      <section className="face-outcome">
        <h1>{title}</h1>
        {phase === 'failed' ? (
          <p className="error" role="alert">{failure}</p>
        ) : (
          <div className="rejected">
            <h2>{f.rejectedTitle}</h2>
            <ul className="checks">
              {rejected.map((item) => (
                <li key={item.name} className={item.passed ? 'met' : 'missing'}>
                  <span className="mark" aria-hidden="true">{item.passed ? '✓' : '✗'}</span> {checkLine(item, t)}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="actions">
          <button type="button" onClick={onChoice}>{again}</button>
          <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
        </div>
      </section>
    )

  return (
    <section className="enrolment face-verification">
      <h1>{title}</h1>
      {mode === 'live' ? (
        <>
          <p className="aside">{f.guide.noFace}</p>
          <CameraPanel busy={phase !== 'ready'} minimumWidth={minimumWidth} onTaken={(image) => void check(image, 'device')} />
        </>
      ) : (
        <div className={`drop-zone${dragging ? ' dragging' : ''}`}>
          <p><strong>{dragging ? f.files.drop : f.files.dropZone}</strong></p>
          <p className="aside">{f.files.uploadNote}</p>
          <button type="button" disabled={phase !== 'ready'} onClick={() => input.current?.click()}>{f.files.choose}</button>
          <input ref={input} type="file" accept="image/jpeg,image/png" hidden data-testid="face-file"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? [])
              event.target.value = ''
              void takeFile(files)
            }} />
        </div>
      )}
      {notice && <p className="error" role="alert">{notice}</p>}
      <p className="notice prompt" role="status" aria-live="polite">{phase === 'checking' ? comparing : ''}</p>
      <button type="button" className="secondary" onClick={onChoice}>{f.cancel}</button>
    </section>
  )
}
