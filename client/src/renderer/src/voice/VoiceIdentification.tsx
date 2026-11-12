// H56: voice identification (1:N), as H50 does for the face and H55 for the voice's 1:1. ECAPA-TDNN's card offers the
// live identification and, since H57, an existing recording from a file (H27); the microphone opens only on that
// choice (H40). A recording that fails its checks makes no attempt and ends on its own outcome screen. The server ranks every
// current voice enrolment of the active users by its highest similarity, saves the attempt with its sealed recording,
// and only then answers. Other users stay anonymous, without a recording or a name, and only the caller's own enrolled
// recording is sent and can be played (H18). The search itself is one database query of a few milliseconds, so the
// pass over the gallery plays once when the answer arrives (GalleryPass.tsx); "Identify again" returns to the choice.
import { useState, type ComponentType } from 'react'
import type { VoiceCheck, VoiceIdentificationAnswer, VoiceIdentificationResult, VoiceMethod, VoiceSource } from '../../../shared/bridge'
import { GalleryPass, usePass } from '../GalleryPass'
import { errorText } from '../texts'
import { useSession } from '../session'
import { MicrophonePanel, type PanelProps, type Recorded } from './MicrophonePanel'
import { RecordingRow } from './Recording'
import { VoiceChecks } from './VoiceEnrolment'
import { VoiceFile, VoiceSourceLine } from './VoiceFile'
import { VoiceNotEnrolled } from './VoiceVerification'
import { pcmOfWav } from './wav'

function Title() {
  const { t } = useSession()
  return <>{t.voice.identify.title} <bdi dir="ltr">(1:N)</bdi></>
}

export function VoiceIdentificationView({ result, probe, rate, onAgain, onLeave }: {
  result: VoiceIdentificationResult
  probe: Int16Array
  rate: number
  onAgain: () => void
  onLeave: () => void
}) {
  const { t } = useSession()
  const v = t.voice
  const n = v.identify
  const [passing, heading] = usePass()

  const gallery = <p>{n.gallery(result.enrolments, result.gallery_size)}</p>
  if (passing)
    return (
      <section className="voice-identification">
        <h1><Title /></h1>
        <GalleryPass comparing={n.comparing}>{gallery}</GalleryPass>
      </section>
    )

  const leader = result.candidates[0]
  return (
    <section className="voice-identification">
      <h1 ref={heading} tabIndex={-1}>{result.accepted ? n.found : n.notFound}</h1>
      {result.accepted && leader && (
        <p><strong>{result.tied_leaders > 1 ? n.tie(result.tied_leaders) : leader.own ? n.you : n.otherUser}</strong></p>
      )}
      <meter className="face-score" min={0} max={1} value={Math.max(0, result.score)} aria-label={v.verify.scoreLabel} />
      <p className={result.accepted ? 'ok' : 'error'}>{n.score(result.score, result.threshold)}</p>
      <div className="table-wrap">
        <table>
          <caption>{n.ranking(result.candidates.length, result.enrolments)}</caption>
          <thead><tr><th>{n.rank}</th><th>{n.candidate}</th><th>{v.verify.scoreLabel}</th><th>{n.decision}</th></tr></thead>
          <tbody>{result.candidates.map((candidate) => (
            <tr key={candidate.rank} className={candidate.own ? 'own' : undefined}>
              <td>{candidate.rank}</td>
              <td>{candidate.own ? n.you : n.otherUser}</td>
              <td><bdi dir="ltr">{candidate.score.toFixed(3)}</bdi></td>
              <td>{candidate.accepted ? v.above : v.notAbove}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {result.view ? (
        <>
          <p>{n.shownBeside(result.view.rank)}</p>
          <ul className="recordings">
            <RecordingRow label={v.verify.newRecording} waveformLabel={v.verify.newRecording} pcm={probe} rate={rate} />
            <RecordingRow label={n.yourRecording(result.view.placement)} waveformLabel={n.yourRecording(result.view.placement)}
              pcm={pcmOfWav(result.view.reference)} rate={rate} />
          </ul>
        </>
      ) : (
        <p className="aside">{n.noView}</p>
      )}
      {gallery}
      <p className="aside">{n.privacy}</p>
      <p className="aside">{v.verify.time(result.duration_ms)} {v.verify.saved}</p>
      <VoiceSourceLine source={result.source} file={result.file} />
      <div className="actions">
        <button type="button" onClick={onAgain}>{n.again}</button>
        <button type="button" className="secondary" onClick={onLeave}>{v.back}</button>
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
  | { kind: 'identified'; result: VoiceIdentificationResult; probe: Int16Array }

interface Props {
  method: VoiceMethod
  enrolled: boolean
  onEnrol(): void
  onLeave(): void
  Panel?: ComponentType<PanelProps> // the microphone; the tests give a stand-in, since jsdom has no audio
}

export function VoiceIdentification({ method, enrolled, onEnrol, onLeave, Panel = MicrophonePanel }: Props) {
  const { call, t } = useSession()
  const v = t.voice
  const n = v.identify
  const [stage, setStage] = useState<Stage>({ kind: 'choice' })

  if (!enrolled) return <VoiceNotEnrolled title={<Title />} text={n.notEnrolled} onEnrol={onEnrol} />

  // The page's own samples of a recording from the microphone; for a file, the recording the server compared (H57).
  async function identify(recording: string, source: VoiceSource, pcm?: Int16Array) {
    setStage({ kind: source === 'file' ? 'file' : 'live', busy: true })
    const answer = await call<VoiceIdentificationAnswer>('identifyVoice', source === 'file' ? { recording, source } : { recording })
    if (!answer.ok) setStage({ kind: 'failed', text: n.errors[answer.error] ?? v.errors[answer.error] ?? errorText(answer, t) })
    else if (answer.data.status === 'rejected') setStage({ kind: 'rejected', checks: answer.data.checks })
    else setStage({ kind: 'identified', result: answer.data, probe: pcm ?? pcmOfWav(answer.data.probe ?? '') })
  }

  const again = () => setStage({ kind: 'choice' })
  if (stage.kind === 'identified')
    return <VoiceIdentificationView key={stage.result.attempt_id} result={stage.result} probe={stage.probe} rate={method.sample_rate}
      onAgain={again} onLeave={onLeave} />
  return (
    <section className="voice-identification">
      <h1><Title /></h1>
      {stage.kind === 'choice' && (
        <>
          <div className="setting method-card">
            <h2>ECAPA-TDNN</h2>
            <p>{n.lead}</p>
            <p className="aside">{v.methodThreshold(method.threshold)}</p>
            <p className="aside">{n.privacy}</p>
            <p className="aside">{n.speed}</p>
          </div>
          <div className="actions">
            <button type="button" onClick={() => setStage({ kind: 'live', busy: false })}>{n.live}</button>
            <button type="button" className="secondary" onClick={() => setStage({ kind: 'file', busy: false })}>{v.files.upload}</button>
            <button type="button" className="secondary" onClick={onLeave}>{v.back}</button>
          </div>
          <p className="aside">{v.files.uploadNote}</p>
        </>
      )}
      {stage.kind === 'live' && (
        <>
          <Panel busy={stage.busy} seconds={method.recording_seconds} rate={method.sample_rate}
            sentence={v.sentences[v.sentences.length - 1]!}
            onRecorded={(recorded: Recorded) => void identify(recorded.recording, 'device', recorded.pcm)} />
          <p className="notice prompt" role="status" aria-live="polite">{stage.busy ? n.comparing : ''}</p>
          <button type="button" className="secondary" disabled={stage.busy} onClick={again}>{v.cancel}</button>
        </>
      )}
      {stage.kind === 'file' && (
        <>
          <VoiceFile busy={stage.busy} onFile={(recording) => void identify(recording, 'file')} />
          <p className="notice prompt" role="status" aria-live="polite">{stage.busy ? n.comparing : ''}</p>
          <button type="button" className="secondary" disabled={stage.busy} onClick={again}>{v.cancel}</button>
        </>
      )}
      {stage.kind === 'rejected' && (
        <div className="rejected">
          <h2>{v.verify.rejectedTitle}</h2>
          <VoiceChecks checks={stage.checks} />
        </div>
      )}
      {stage.kind === 'failed' && <p className="error" role="alert">{stage.text}</p>}
      {(stage.kind === 'rejected' || stage.kind === 'failed') && (
        <div className="actions">
          <button type="button" onClick={again}>{n.again}</button>
          <button type="button" className="secondary" onClick={onLeave}>{v.back}</button>
        </div>
      )}
    </section>
  )
}
