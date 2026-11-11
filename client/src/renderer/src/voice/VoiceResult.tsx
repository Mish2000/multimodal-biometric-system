// H54: the enrolled voice, once, from the server's answer and the page's own recordings: the three kept
// recordings with their waveforms, a button to hear each, their checks, how alike each pair is against the
// threshold, and what was stored. The page keeps them only while this screen is open.
import type { VoiceSaved } from '../../../shared/bridge'
import { useSession } from '../session'
import { RecordingCard } from './Recording'
import { VoiceChecks, VoicePairs, type KeptRecording } from './VoiceEnrolment'

export function VoiceResult({ saved, kept, rate, onDone }: { saved: VoiceSaved; kept: KeptRecording[]; rate: number; onDone: () => void }) {
  const { t } = useSession()
  const v = t.voice
  const length = saved.templates[0]?.embedding_length ?? 0
  return (
    <section className="voice-result">
      <h1>{v.savedTitle}</h1>
      <p className="lead">{v.savedLead(saved.threshold)}</p>
      {saved.enrolment.replaced_previous && <p className="aside">{v.replacedPrevious}</p>}
      <ul className="recordings">
        {saved.samples.map((sample) => {
          const own = kept.find((item) => item.number === sample.placement)
          return own ? (
            <RecordingCard key={sample.id} number={sample.placement} pcm={own.pcm} rate={rate} />
          ) : null
        })}
      </ul>
      <p className="aside">{v.waveformNote}</p>
      <h2>{v.checksTitle}</h2>
      {saved.samples.map((sample) => (
        <div key={sample.id}>
          <h3>{v.recordingN(sample.placement)}</h3>
          <VoiceChecks checks={sample.checks} />
        </div>
      ))}
      <h2>{v.pairsTitle}</h2>
      <VoicePairs pairs={saved.pairs} threshold={saved.threshold} />
      {saved.not_kept.length > 0 && <p className="aside">{v.notKept(saved.not_kept.join(', '))}</p>}
      <p>{v.stored(saved.samples.length, length)}</p>
      <div className="actions">
        <button type="button" onClick={onDone}>{v.done}</button>
      </div>
    </section>
  )
}
