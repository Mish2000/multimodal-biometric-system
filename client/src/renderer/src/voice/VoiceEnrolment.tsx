// H54: the voice's enrolment. The page records; every recording is checked by the server at once, and once three
// have passed, they are sent together. The server keeps the voice when three of them match each other above
// SpeechBrain's threshold; otherwise the user records another, up to six kept recordings or twelve made. Each
// recording shows another sentence to read; the model does not depend on the words.
import { useState, type ComponentType } from 'react'
import type { ApiResult, VoiceCheck, VoiceCheckResult, VoiceEnrolmentAnswer, VoiceMethod, VoicePair, VoiceSaved } from '../../../shared/bridge'
import { errorText, type Texts } from '../texts'
import { useSession } from '../session'
import { MicrophonePanel, type PanelProps, type Recorded } from './MicrophonePanel'
import { RecordingCard } from './Recording'

export const MOST_MADE = 12 // recordings made in one enrolment, kept or not (as the face's images)

export interface KeptRecording extends Recorded {
  number: number // in the order kept, from 1, as the server numbers them
}

type Shown = { kind: 'rejected'; checks: VoiceCheck[] } | { kind: 'kept'; number: number } | { kind: 'another' } | null

export function checkLine(check: VoiceCheck, t: Texts): string {
  const v = t.voice
  const name = v.checks[check.name] ?? check.name
  if (check.name === 'length') return `${name}: ${v.lengthDetail(check.seconds ?? 0, check.minimum ?? 0, check.maximum ?? 0)}`
  if (check.name === 'speech') return `${name}: ${v.speechDetail(check.seconds ?? 0, check.minimum ?? 0, check.above_noise)}`
  if (check.name === 'clipping') return `${name}: ${v.clippingDetail(check.share ?? 0, check.maximum ?? 0)}`
  return name
}

export function VoiceChecks({ checks }: { checks: VoiceCheck[] }) {
  const { t } = useSession()
  return (
    <ul className="checks">
      {checks.map((item) => (
        <li key={item.name} className={item.passed ? 'met' : 'missing'}>
          <span className="mark" aria-hidden="true">{item.passed ? '✓' : '✗'}</span> {checkLine(item, t)}
        </li>
      ))}
    </ul>
  )
}

export function VoicePairs({ pairs, threshold }: { pairs: VoicePair[]; threshold: number }) {
  const { t } = useSession()
  const v = t.voice
  return (
    <ul className="checks">
      {pairs.map((pair) => (
        <li key={`${pair.reference}-${pair.probe}`} className={pair.accepted ? 'met' : 'missing'}>
          <span className="mark" aria-hidden="true">{pair.accepted ? '✓' : '✗'}</span>
          <strong>{v.pair(pair.probe, pair.reference)}</strong>{' '}
          <bdi dir="ltr">{pair.score.toFixed(3)}</bdi>{' '}
          <span className="aside">
            {pair.accepted ? v.above : v.notAbove} (<bdi dir="ltr">{threshold}</bdi>)
          </span>
        </li>
      ))}
    </ul>
  )
}

interface Props {
  method: VoiceMethod
  onSaved(saved: VoiceSaved, kept: KeptRecording[]): void
  onLeave(): void
  Panel?: ComponentType<PanelProps> // the microphone; the tests give a stand-in, since jsdom has no audio
}

export function VoiceEnrolment({ method, onSaved, onLeave, Panel = MicrophonePanel }: Props) {
  const { call, t } = useSession()
  const v = t.voice
  const [kept, setKept] = useState<KeptRecording[]>([])
  const [made, setMade] = useState(0)
  const [phase, setPhase] = useState<'live' | 'checking' | 'saving' | 'failed'>('live')
  const [shown, setShown] = useState<Shown>(null)
  const [pairs, setPairs] = useState<VoicePair[]>([])
  const [failure, setFailure] = useState('')

  function fail(code: string, result?: ApiResult) {
    setPhase('failed')
    setFailure(v.errors[code] ?? (result ? errorText(result, t) : t.unexpected))
  }

  function next(count: number) {
    if (count >= MOST_MADE) fail('too_many_recordings')
    else setPhase('live')
  }

  async function check(recorded: Recorded) {
    const count = made + 1
    setMade(count)
    setPhase('checking')
    const answer = await call<VoiceCheckResult>('checkVoice', { recording: recorded.recording })
    if (!answer.ok) return fail(answer.error, answer)
    if (!answer.data.passed) {
      setShown({ kind: 'rejected', checks: answer.data.checks })
      return next(count)
    }
    const now = [...kept, { ...recorded, number: kept.length + 1 }]
    setKept(now)
    setShown({ kind: 'kept', number: now.length })
    if (now.length < method.recordings) return next(count)
    setPhase('saving')
    const enrolled = await call<VoiceEnrolmentAnswer>('enrolVoice', {
      recordings: now.map((item) => ({ recording: item.recording, captured_at: item.capturedAt })),
    })
    if (!enrolled.ok) return fail(enrolled.error, enrolled)
    if (enrolled.data.status === 'saved') return onSaved(enrolled.data, now)
    setPairs(enrolled.data.pairs)
    if (enrolled.data.status === 'failed') return fail(enrolled.data.error)
    setShown({ kind: 'another' })
    next(count)
  }

  const restart = () => {
    setKept([])
    setMade(0)
    setPairs([])
    setShown(null)
    setFailure('')
    setPhase('live')
  }

  const sentence = v.sentences[made % v.sentences.length]!
  const position = Math.min(kept.length + 1, method.most_kept)
  return (
    <section className="enrolment voice-enrolment">
      <h1>{v.enrolling}</h1>
      <p className="lead">{v.recordingOf(position, Math.max(method.recordings, position))}</p>
      <p className="aside">{v.between}</p>
      <ol className="placements" aria-label={v.keptTitle}>
        {Array.from({ length: Math.max(method.recordings, kept.length) }, (_, i) => (
          <li key={i} className={i < kept.length ? 'kept' : i === kept.length ? 'now' : ''} />
        ))}
      </ol>
      {phase === 'failed' ? (
        <>
          <p className="error" role="alert">{failure}</p>
          <div className="actions">
            <button type="button" onClick={restart}>{v.tryAgain}</button>
            <button type="button" className="secondary" onClick={onLeave}>{v.back}</button>
          </div>
        </>
      ) : (
        <>
          <Panel busy={phase !== 'live'} seconds={method.recording_seconds} rate={method.sample_rate} sentence={sentence}
            onRecorded={(recorded) => void check(recorded)} />
          <p className="notice prompt" role="status" aria-live="polite">
            {phase === 'checking' ? v.checking : phase === 'saving' ? v.saving : shown?.kind === 'kept' ? v.kept(shown.number) : shown?.kind === 'another' ? v.another : ''}
          </p>
          {shown?.kind === 'rejected' && (
            <div className="rejected">
              <p>{v.rejected}</p>
              <VoiceChecks checks={shown.checks} />
            </div>
          )}
          <button type="button" className="secondary" onClick={onLeave}>{v.cancel}</button>
        </>
      )}
      {kept.length > 0 && (
        <>
          <h2>{v.keptTitle}</h2>
          <ul className="recordings">
            {kept.map((item) => <RecordingCard key={item.number} number={item.number} pcm={item.pcm} rate={method.sample_rate} />)}
          </ul>
        </>
      )}
      {pairs.length > 0 && (
        <>
          <h2>{v.pairsTitle}</h2>
          <VoicePairs pairs={pairs} threshold={method.threshold} />
        </>
      )}
    </section>
  )
}
