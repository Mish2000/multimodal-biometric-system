// H49, H50: the pieces that face verification and identification share. Before an enrolment, the message of H15;
// SFace's card, without a choice, and an explicit start (H40); then the camera panel of H48 for one image that
// the server compares. An image that fails its checks is taken again and makes no attempt, at most twelve per
// run (as H35); the server's answer is either such a rejection or the completed, saved result.
// H51: an image file may take the camera's place here, and only here (H27). It stays out of sight: a small
// "more options" button beside the camera opens a menu with one item, and a file dragged over the window shows
// the drop target only while it is dragged. The page checks only the size; it sends the file's content alone,
// never its name, and the server decides by the content.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import type { FaceCheck, FaceDetection, FaceMethod, FaceSize, FaceSource, RouteName } from '../../../shared/bridge'
import { errorText } from '../texts'
import { useSession } from '../session'
import { CameraPanel } from './CameraPanel'
import { checkLine, MOST_TAKEN } from './FaceEnrolment'

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

export function FaceCard({ title, lead, method, notes, start, onStart, onLeave }: {
  title: ReactNode
  lead: string
  method: FaceMethod
  notes: string[]
  start: string
  onStart: () => void
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
        <button type="button" disabled={!method.available} onClick={onStart}>{start}</button>
        <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
      </div>
    </section>
  )
}

type Rejected = { status: 'rejected'; checks: FaceCheck[] } & FaceDetection

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

export function FaceTake<T extends { status: string }>({ title, route, minimumWidth, comparing, errors, onResult, onLeave }: {
  title: ReactNode
  route: Extract<RouteName, 'verifyFace' | 'identifyFace'>
  minimumWidth: number
  comparing: string
  errors?: Record<string, string>
  onResult: (result: T) => void
  onLeave: () => void
}) {
  const { call, t } = useSession()
  const f = t.face
  const [phase, setPhase] = useState<'live' | 'checking' | 'failed'>('live')
  const [taken, setTaken] = useState(0)
  const [rejected, setRejected] = useState<FaceCheck[] | null>(null)
  const [failure, setFailure] = useState('')
  const [notice, setNotice] = useState('') // a file the page itself could not use (H51)
  const [menu, setMenu] = useState(false)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const options = useRef<HTMLDivElement>(null)
  const latestFile = useRef<(files: File[]) => void>(() => undefined)

  async function takeFile(files: File[]) {
    setMenu(false)
    setNotice('')
    const [file] = files
    if (phase !== 'live' || file === undefined) return
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

  // H51: a file dragged over the window shows the drop target only while it is dragged; the browser's own
  // handling (opening the file in the window) is always prevented here.
  useEffect(() => {
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
  }, [])

  // The menu closes on Escape and on a click outside it.
  useEffect(() => {
    if (!menu) return
    const outside = (event: PointerEvent) => {
      if (!options.current?.contains(event.target as Node)) setMenu(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenu(false)
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [menu])

  async function check(image: string, source: FaceSource = 'device') {
    const count = taken + 1
    setTaken(count)
    setRejected(null)
    setNotice('')
    setPhase('checking')
    const answer = await call<T | Rejected>(route, { image, source })
    if (!answer.ok) {
      setPhase('failed')
      setFailure(errors?.[answer.error] ?? f.errors[answer.error] ?? errorText(answer, t))
      return
    }
    if (answer.data.status !== 'rejected') {
      onResult(answer.data as T)
      return
    }
    setRejected((answer.data as Rejected).checks)
    if (count >= MOST_TAKEN) {
      setPhase('failed')
      setFailure(f.errors.too_many_images ?? t.unexpected)
    } else setPhase('live')
  }

  return (
    <section className="enrolment face-verification">
      <h1>{title}</h1>
      <p className="aside">{f.guide.noFace}</p>
      {phase === 'failed' ? (
        <>
          <p className="error" role="alert">{failure}</p>
          <div className="actions">
            <button type="button" onClick={() => {
              setTaken(0)
              setRejected(null)
              setPhase('live')
            }}>{f.tryAgain}</button>
            <button type="button" className="secondary" onClick={onLeave}>{f.back}</button>
          </div>
        </>
      ) : (
        <>
          <CameraPanel busy={phase !== 'live'} minimumWidth={minimumWidth} onTaken={(image) => void check(image)} />
          <div className="more-options" ref={options}>
            <button type="button" className="more-button secondary" aria-label={f.files.more} title={f.files.more}
              aria-haspopup="menu" aria-expanded={menu} disabled={phase !== 'live'} onClick={() => setMenu((open) => !open)}>⋯</button>
            {menu && (
              <div className="more-menu" role="menu">
                <button type="button" role="menuitem" autoFocus onClick={() => input.current?.click()}>
                  <span>{f.files.use}</span>{' '}
                  <small>{f.files.hint}</small>
                </button>
              </div>
            )}
            <input ref={input} type="file" accept="image/jpeg,image/png" hidden data-testid="face-file"
              onChange={(event) => {
                const files = Array.from(event.target.files ?? [])
                event.target.value = ''
                void takeFile(files)
              }} />
          </div>
          {notice && <p className="error" role="alert">{notice}</p>}
          <p className="notice prompt" role="status" aria-live="polite">{phase === 'checking' ? comparing : ''}</p>
          {rejected !== null && (
            <div className="rejected">
              <p>{f.rejected}</p>
              <ul className="checks">
                {rejected.map((item) => (
                  <li key={item.name} className={item.passed ? 'met' : 'missing'}>
                    <span className="mark" aria-hidden="true">{item.passed ? '✓' : '✗'}</span> {checkLine(item, t)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button type="button" className="secondary" onClick={onLeave}>{f.cancel}</button>
        </>
      )}
      {dragging && phase === 'live' && (
        <div className="drop-target" aria-hidden="true">
          <p><strong>{f.files.drop}</strong></p>
          <p className="aside">{f.files.dropHint}</p>
        </div>
      )}
    </section>
  )
}
