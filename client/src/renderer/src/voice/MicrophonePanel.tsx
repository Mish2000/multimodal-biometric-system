// H54: the microphone of the voice screens, chosen by the client: the sentence to read, a level meter of the
// current microphone, a selector when more than one can be used, the recording with its timer, and what happened
// when a microphone was silent, unplugged or refused. Nothing is stored here: a recording goes to the screen
// that asked for it.
import { useEffect, useEffectEvent, useState } from 'react'
import { useSession } from '../session'
import { Notice } from '../ui/Notice'
import { openMicrophone, problemOf, record, type MicrophoneInput, type MicrophoneProblem } from './input'
import { looksSilent, SILENT_SECONDS, type Microphone } from './microphone'
import { useMicrophones } from './useMicrophones'
import { base64Of, levelOf, toPcm16, wavBytes } from './wav'

export interface Recorded {
  recording: string // the WAV, in base64
  capturedAt: string
  pcm: Int16Array // kept by the page for the waveform and the playback
}

export interface PanelProps {
  busy: boolean // the page is waiting for the server, so nothing is recorded
  seconds: number
  rate: number
  sentence: string
  onRecorded(recorded: Recorded): void
}

const BARS = 24
const FLOOR_DB = -60 // the meter's empty end; its full end is 0 dB of full scale
const UPDATE_MS = 60

function MicrophoneView({ microphone, busy, seconds, rate, sentence, onRecorded, onSilent, onEnded, onProblem }: PanelProps & {
  microphone: Microphone
  onSilent(): void
  onEnded(): void
  onProblem(problem: MicrophoneProblem): void
}) {
  const { t } = useSession()
  const v = t.voice
  const [input, setInput] = useState<MicrophoneInput | null>(null)
  const [level, setLevel] = useState(-100)
  const [progress, setProgress] = useState<number | null>(null) // while recording, from 0 to 1
  // The latest handlers, for what the microphone reports after it was opened.
  const reportSilent = useEffectEvent(() => onSilent())
  const reportEnded = useEffectEvent(() => onEnded())
  const reportProblem = useEffectEvent((problem: MicrophoneProblem) => onProblem(problem))

  // The microphone: opened for this view, closed when the view goes. Another microphone or rate is another view (its
  // key), which starts afresh.
  useEffect(() => {
    let active = true
    let opened: MicrophoneInput | null = null
    openMicrophone(microphone.deviceId, rate)
      .then((microphoneInput) => {
        if (!active) return microphoneInput.close()
        opened = microphoneInput
        microphoneInput.onEnded(() => reportEnded())
        let peak = 0
        let heard = 0
        let window: Float32Array[] = []
        let shown = 0
        microphoneInput.onBlock((block) => {
          if (heard < SILENT_SECONDS) {
            for (let i = 0; i < block.length; i += 1) peak = Math.max(peak, Math.abs(block[i]!))
            heard += block.length / microphoneInput.rate
            if (looksSilent(peak, heard)) reportSilent()
          }
          window.push(block)
          const now = performance.now()
          if (now - shown < UPDATE_MS) return
          shown = now
          const joined = new Float32Array(window.reduce((sum, part) => sum + part.length, 0))
          let at = 0
          for (const part of window) {
            joined.set(part, at)
            at += part.length
          }
          window = []
          setLevel(levelOf(joined))
        })
        setInput(microphoneInput)
      })
      .catch((error: unknown) => {
        if (active) reportProblem(problemOf(error))
      })
    return () => {
      active = false
      opened?.close()
    }
  }, [microphone.deviceId, rate])

  async function start() {
    if (input === null) return
    const capturedAt = new Date().toISOString()
    setProgress(0)
    const samples = await record(input, seconds, setProgress)
    setProgress(null)
    const pcm = toPcm16(samples)
    onRecorded({ recording: base64Of(wavBytes(pcm, input.rate)), capturedAt, pcm })
  }

  const lit = Math.round(Math.max(0, Math.min(1, (level - FLOOR_DB) / -FLOOR_DB)) * BARS)
  const recording = progress !== null
  return (
    <div className={`microphone${recording ? ' recording' : ''}`}>
      <p className="sentence">
        <span className="aside">{v.read}</span> <q>{sentence}</q>
      </p>
      <div className="level" role="meter" aria-label={v.level} aria-valuemin={FLOOR_DB} aria-valuemax={0}
        aria-valuenow={Math.round(Math.max(FLOOR_DB, level))} aria-valuetext={v.levelText(Math.round(level))}>
        {Array.from({ length: BARS }, (_, i) => <i key={i} className={i < lit ? (i >= BARS - 2 ? 'on loud' : 'on') : ''} />)}
      </div>
      {recording ? (
        <div className="timer" role="timer" aria-live="off">
          <span>{v.timer((progress ?? 0) * seconds, seconds)}</span>
          <span className="track"><span className="run" style={{ inlineSize: `${Math.round((progress ?? 0) * 100)}%` }} /></span>
        </div>
      ) : (
        <p className="aside">{input === null ? v.starting : v.howLong(seconds)}</p>
      )}
      <div className="actions">
        <button type="button" className="primary" disabled={busy || input === null || recording} onClick={() => void start()}>
          {recording ? v.recording : v.record}
        </button>
      </div>
    </div>
  )
}

export function MicrophonePanel(props: PanelProps) {
  const { t } = useSession()
  const v = t.voice
  const choice = useMicrophones()
  const [notice, setNotice] = useState('')
  const [problem, setProblem] = useState<{ microphone: string; text: string } | null>(null)

  function lost(microphone: Microphone, text: string) {
    setNotice(text)
    setProblem(null)
    choice.markSilent(microphone)
  }

  function refused(microphone: Microphone, kind: MicrophoneProblem) {
    const text = kind === 'busy' ? v.microphoneBusy : kind === 'denied' ? v.microphoneDenied : v.microphoneFailed
    setProblem({ microphone: microphone.key, text })
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
            {v.microphone}{' '}
            <select value={current.key} onChange={(event) => {
              const microphone = choice.usable.find((item) => item.key === event.target.value)
              if (microphone) {
                setNotice('')
                choice.pick(microphone)
              }
            }}>
              {choice.usable.map((microphone) => (
                <option key={microphone.key} value={microphone.key}>{microphone.name}</option>
              ))}
            </select>
          </label>
        </div>
      )}
      {notice && <Notice role="status">{notice}</Notice>}
      {choice.microphones === null ? (
        <p className="aside">{v.starting}</p>
      ) : current === null ? (
        <>
          <Notice tone="alert" role="alert">{choice.microphones.length > 0 ? v.allSilent : v.noMicrophone}</Notice>
          <button type="button" className="primary" onClick={retry}>{v.retryMicrophones}</button>
        </>
      ) : problem !== null && problem.microphone === current.key ? (
        <>
          <Notice tone="alert" role="alert">{problem.text}</Notice>
          <button type="button" className="primary" onClick={retry}>{v.retryMicrophones}</button>
        </>
      ) : (
        <MicrophoneView
          key={`${current.deviceId} ${props.rate}`}
          microphone={current}
          {...props}
          onSilent={() => lost(current, v.silent(current.name))}
          onEnded={() => lost(current, v.disconnected(current.name))}
          onProblem={(kind) => refused(current, kind)}
        />
      )}
    </>
  )
}
