// H54: a recording as the page shows it: its waveform, drawn from the page's own samples, and a button that plays
// it through the speakers. The samples stay in the page's memory while the screen is open.
import { useState } from 'react'
import { useSession } from '../session'
import { envelope } from './wav'

const COLUMNS = 160
const HEIGHT = 48

// Drawn to the recording's own loudest sample, so a quiet recording shows its shape as clearly as a loud one.
export function Waveform({ pcm, label }: { pcm: Int16Array; label: string }) {
  const columns = envelope(pcm, COLUMNS)
  const peak = Math.max(1 / 64, ...columns.map(([low, high]) => Math.max(-low, high)))
  const middle = HEIGHT / 2
  const reach = (0.9 * middle) / peak
  const path = columns
    .map(([low, high], c) => `M${c + 0.5} ${(middle - Math.max(high * reach, 0.5)).toFixed(1)}V${(middle - Math.min(low * reach, -0.5)).toFixed(1)}`)
    .join('')
  return (
    <svg className="waveform" viewBox={`0 0 ${COLUMNS} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <path d={path} />
    </svg>
  )
}

export function canPlay(): boolean {
  return typeof AudioContext !== 'undefined'
}

async function play(pcm: Int16Array, rate: number): Promise<void> {
  const context = new AudioContext()
  try {
    const buffer = context.createBuffer(1, pcm.length, rate)
    const samples = new Float32Array(pcm.length)
    for (let i = 0; i < pcm.length; i += 1) samples[i] = pcm[i]! / 32768
    buffer.copyToChannel(samples, 0)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    await new Promise<void>((resolve) => {
      source.onended = () => resolve()
      source.start()
    })
  } finally {
    void context.close()
  }
}

export function PlayButton({ pcm, rate }: { pcm: Int16Array; rate: number }) {
  const { t } = useSession()
  const v = t.voice
  const [playing, setPlaying] = useState(false)
  return (
    <button type="button" className="secondary" disabled={playing || !canPlay()} onClick={() => {
      setPlaying(true)
      void play(pcm, rate).finally(() => setPlaying(false))
    }}>
      {playing ? v.playing : v.play}
    </button>
  )
}

export function RecordingRow({ label, waveformLabel, pcm, rate }: { label: string; waveformLabel: string; pcm: Int16Array; rate: number }) {
  return (
    <li className="recording-row">
      <span>{label}</span>
      <Waveform pcm={pcm} label={waveformLabel} />
      <PlayButton pcm={pcm} rate={rate} />
    </li>
  )
}

export function RecordingCard({ number, pcm, rate }: { number: number; pcm: Int16Array; rate: number }) {
  const { t } = useSession()
  const v = t.voice
  return <RecordingRow label={v.recordingN(number)} waveformLabel={v.waveformOf(number)} pcm={pcm} rate={rate} />
}
