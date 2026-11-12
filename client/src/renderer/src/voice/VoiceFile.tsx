// H57: an existing recording instead of the microphone, for 1:1 and 1:N only, on a screen of its own (as H53 has it for
// the face): a visible drop zone, a button that chooses a file, and the rules. One file at a time; the page checks only
// its size and sends its content alone, never its name, and the server and the engine decide by the content.
import { useEffect, useRef, useState } from 'react'
import type { VoiceFile as FileFacts, VoiceSource } from '../../../shared/bridge'
import { useSession } from '../session'

export const FILE_BYTES = 10 * 1024 * 1024 // H27

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes('Files')

function base64Of(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

export function VoiceFile({ busy, onFile }: { busy: boolean; onFile: (recording: string) => void }) {
  const { t } = useSession()
  const files = t.voice.files
  const [dragging, setDragging] = useState(false)
  const [notice, setNotice] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const latest = useRef<(chosen: File[]) => void>(() => undefined)

  async function take(chosen: File[]) {
    setNotice('')
    const [file] = chosen
    if (busy || file === undefined) return
    if (chosen.length > 1) return setNotice(files.oneFile)
    if (file.size > FILE_BYTES) return setNotice(files.tooLarge)
    let recording: string
    try {
      recording = await base64Of(file)
    } catch {
      return setNotice(files.unreadable)
    }
    onFile(recording)
  }
  latest.current = (chosen) => void take(chosen)

  // A file dragged over the window marks the drop zone and is taken when dropped; the browser's own handling (opening
  // the file in the window) is prevented.
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
      latest.current(Array.from(event.dataTransfer?.files ?? []))
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

  return (
    <>
      <div className={`drop-zone${dragging ? ' dragging' : ''}`}>
        <p><strong>{dragging ? files.drop : files.dropZone}</strong></p>
        <p className="aside">{files.uploadNote}</p>
        <button type="button" disabled={busy} onClick={() => input.current?.click()}>{files.choose}</button>
        <input ref={input} type="file" accept=".wav,.mp3,.ogg,.opus,audio/wav,audio/mpeg,audio/ogg" hidden data-testid="voice-file"
          onChange={(event) => {
            const chosen = Array.from(event.target.files ?? [])
            event.target.value = ''
            void take(chosen)
          }} />
      </div>
      {notice && <p className="error" role="alert">{notice}</p>}
    </>
  )
}

// libsndfile's names as people know them: an extended WAV is a WAV, and an OGG names its codec.
function formatName(file: FileFacts): string {
  if (file.format === 'WAVEX') return 'WAV'
  if (file.format === 'OGG') return `OGG (${file.subtype === 'OPUS' ? 'Opus' : 'Vorbis'})`
  return file.format
}

export function VoiceSourceLine({ source, file }: { source: VoiceSource; file?: FileFacts | undefined }) {
  const { t } = useSession()
  return (
    <p className="aside">
      {source === 'file' && file
        ? t.voice.files.fromFile(formatName(file), file.sample_rate, file.channels, file.seconds)
        : t.voice.verify.fromMicrophone}
    </p>
  )
}
