// H55: voice verification (1:1), as H49 does for the face. H53's choice: ECAPA-TDNN's card offers the live
// recording, and since H57 an existing recording from a file; the microphone opens only on that choice (H40). A
// recording that fails its checks makes no attempt and ends on its own outcome screen. The server compares a passing
// recording with the three enrolled ones, saves the attempt with its sealed recording, and only then answers; the
// result shows the new recording beside the closest enrolled one, and "Verify again" returns to the choice.
import { useState, type ComponentType, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import type { VoiceCheck, VoiceMethod, VoiceSource, VoiceVerificationAnswer, VoiceVerificationResult } from '../../../shared/bridge'
import { errorText } from '../texts'
import { useSession } from '../session'
import { Icon } from '../ui/Icon'
import { Notice } from '../ui/Notice'
import { ScoreMeter } from '../ui/ScoreMeter'
import { MicrophonePanel, type PanelProps, type Recorded } from './MicrophonePanel'
import { RecordingRow } from './Recording'
import { VoiceChecks } from './VoiceEnrolment'
import { VoiceFile, VoiceSourceLine } from './VoiceFile'
import { pcmOfWav } from './wav'

// H15: before a voice enrolment, verification and identification (H56) offer the enrolment or the home screen.
export function VoiceNotEnrolled({ title, text, onEnrol }: { title: ReactNode; text: string; onEnrol: () => void }) {
  const { t } = useSession()
  const navigate = useNavigate()
  const v = t.voice.verify
  return (
    <section>
      <h1>{title}</h1>
      <Notice role="status" still>{text}</Notice>
      <div className="actions">
        <button type="button" className="primary" onClick={onEnrol}>{v.enrolNow}</button>
        <button type="button" className="quiet" onClick={() => navigate('/')}>{v.home}</button>
      </div>
    </section>
  )
}

export function VoiceVerificationView({ result, probe, rate, onAgain, onLeave }: {
  result: VoiceVerificationResult
  probe: Int16Array
  rate: number
  onAgain: () => void
  onLeave: () => void
}) {
  const { t } = useSession()
  const v = t.voice.verify
  return (
    <section className="voice-verification-result">
      <h1 className="display">{result.accepted ? v.match : v.noMatch}</h1>
      <ul className="recordings">
        <RecordingRow label={v.newRecording} waveformLabel={v.newRecording} pcm={probe} rate={rate} />
        <RecordingRow label={v.enrolledRecording(result.view.placement)} waveformLabel={v.enrolledRecording(result.view.placement)}
          pcm={pcmOfWav(result.view.reference)} rate={rate} />
      </ul>
      <ScoreMeter score={result.score} threshold={result.threshold} scale="similarity" label={v.scoreLabel}
        shown={result.score.toFixed(3)} thresholdLabel={t.matchAbove(result.threshold)} accepted={result.accepted}
        explanation={v.score(result.score, result.threshold)} />
      <p className="aside">{v.time(result.duration_ms)} {v.saved}</p>
      <VoiceSourceLine source={result.source} file={result.file} />
      <h2>{v.comparisonsTitle}</h2>
      <ul className="checks">
        {result.comparisons.map((comparison) => (
          <li key={comparison.placement} className={comparison.accepted ? 'met' : 'missing'}>
            <Icon name={comparison.accepted ? 'check' : 'alert'} />
            <span>
              <strong>{v.enrolledRecording(comparison.placement)}</strong>{' '}
              <bdi dir="ltr">{comparison.score.toFixed(3)}</bdi>{' '}
              <span className="aside">{comparison.accepted ? t.voice.above : t.voice.notAbove}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="actions">
        <button type="button" className="primary" onClick={onAgain}>{v.again}</button>
        <button type="button" className="quiet" onClick={onLeave}>{v.back}</button>
      </div>
    </section>
  )
}

type Stage =
  | { kind: 'choice' }
  | { kind: 'live'; busy: boolean }
  | { kind: 'file'; busy: boolean } // H57
  | { kind: 'rejected'; checks: VoiceCheck[] }
  | { kind: 'failed'; text: string }
  | { kind: 'verified'; result: VoiceVerificationResult; probe: Int16Array }

interface Props {
  method: VoiceMethod
  enrolled: boolean
  onEnrol(): void
  onLeave(): void
  Panel?: ComponentType<PanelProps> // the microphone; the tests give a stand-in, since jsdom has no audio
}

export function VoiceVerification({ method, enrolled, onEnrol, onLeave, Panel = MicrophonePanel }: Props) {
  const { call, t } = useSession()
  const v = t.voice.verify
  const [stage, setStage] = useState<Stage>({ kind: 'choice' })

  if (!enrolled) return <VoiceNotEnrolled title={v.title} text={v.notEnrolled} onEnrol={onEnrol} />

  // The page's own samples of a recording from the microphone; for a file, the recording the server compared (H57).
  async function verify(recording: string, source: VoiceSource, pcm?: Int16Array) {
    setStage({ kind: source === 'file' ? 'file' : 'live', busy: true })
    const answer = await call<VoiceVerificationAnswer>('verifyVoice', source === 'file' ? { recording, source } : { recording })
    if (!answer.ok) setStage({ kind: 'failed', text: t.voice.errors[answer.error] ?? errorText(answer, t) })
    else if (answer.data.status === 'rejected') setStage({ kind: 'rejected', checks: answer.data.checks })
    else setStage({ kind: 'verified', result: answer.data, probe: pcm ?? pcmOfWav(answer.data.probe ?? '') })
  }

  const again = () => setStage({ kind: 'choice' })
  if (stage.kind === 'verified')
    return <VoiceVerificationView result={stage.result} probe={stage.probe} rate={method.sample_rate} onAgain={again} onLeave={onLeave} />
  return (
    <section className="voice-verification">
      <h1>{v.title}</h1>
      {stage.kind === 'choice' && (
        <>
          <div className="setting method-card">
            <h2>ECAPA-TDNN</h2>
            <p>{v.lead}</p>
            <p className="aside">{t.voice.methodThreshold(method.threshold)}</p>
            <p className="aside">{v.speed}</p>
          </div>
          <div className="actions">
            <button type="button" className="primary" onClick={() => setStage({ kind: 'live', busy: false })}>{v.live}</button>
            <button type="button" className="secondary" onClick={() => setStage({ kind: 'file', busy: false })}>{t.voice.files.upload}</button>
            <button type="button" className="quiet" onClick={onLeave}>{v.back}</button>
          </div>
          <p className="aside">{t.voice.files.uploadNote}</p>
        </>
      )}
      {stage.kind === 'live' && (
        <>
          <Panel busy={stage.busy} seconds={method.recording_seconds} rate={method.sample_rate}
            sentence={t.voice.sentences[t.voice.sentences.length - 1]!}
            onRecorded={(recorded: Recorded) => void verify(recorded.recording, 'device', recorded.pcm)} />
          <div className="prompt" role="status" aria-live="polite">{stage.busy && <Notice tone="busy">{v.comparing}</Notice>}</div>
          <button type="button" className="secondary" disabled={stage.busy} onClick={again}>{t.voice.cancel}</button>
        </>
      )}
      {stage.kind === 'file' && (
        <>
          <VoiceFile busy={stage.busy} onFile={(recording) => void verify(recording, 'file')} />
          <div className="prompt" role="status" aria-live="polite">{stage.busy && <Notice tone="busy">{v.comparing}</Notice>}</div>
          <button type="button" className="secondary" disabled={stage.busy} onClick={again}>{t.voice.cancel}</button>
        </>
      )}
      {stage.kind === 'rejected' && (
        <Notice tone="alert" className="rejected">
          <h2>{v.rejectedTitle}</h2>
          <VoiceChecks checks={stage.checks} />
        </Notice>
      )}
      {stage.kind === 'failed' && <Notice tone="alert" role="alert">{stage.text}</Notice>}
      {(stage.kind === 'rejected' || stage.kind === 'failed') && (
        <div className="actions">
          <button type="button" className="primary" onClick={again}>{v.again}</button>
          <button type="button" className="quiet" onClick={onLeave}>{v.back}</button>
        </div>
      )}
    </section>
  )
}
