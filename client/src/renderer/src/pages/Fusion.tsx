// H60: the combined test of every enrolled modality, as its key screens were approved. The page shows the policy's
// points, then takes the face and the voice, each checked at once by its own route, and only then starts the scan:
// the server compares, fuses and saves the whole test in that one request, so nothing waits on the server between
// steps. The result is the score out of 100, each modality's points of its weight and the samples of the test.
import { useEffect, useRef, useState, type CSSProperties, type RefObject } from 'react'
import { useNavigate } from 'react-router'
import {
  FUSION_MODALITIES, type FaceCheck, type FaceCheckResult, type FaceMethod, type FusionEvent, type FusionMethod,
  type FusionModality, type FusionResult, type FusionSamples, type VoiceCheck, type VoiceCheckResult, type VoiceMethod,
} from '../../../shared/bridge'
import { CameraPanel } from '../face/CameraPanel'
import { checkLine as faceCheckLine } from '../face/FaceEnrolment'
import { Ring } from '../fusion/Ring'
import { useSession } from '../session'
import { errorText, type Texts } from '../texts'
import { Icon } from '../ui/Icon'
import { Notice } from '../ui/Notice'
import { Plate } from '../ui/Plate'
import { Steps } from '../ui/Steps'
import { Tag } from '../ui/Tag'
import { MicrophonePanel, type Recorded } from '../voice/MicrophonePanel'
import { checkLine as voiceCheckLine } from '../voice/VoiceEnrolment'

type Modalities = Record<string, { enrolled: boolean; fingers?: number[] }>
type Loaded = { method: FusionMethod; modalities: Modalities; face: FaceMethod | null; voice: VoiceMethod | null }
type Mode = 'verify' | 'identify'

const OTHERS = ['face', 'voice'] as const

export function Fusion({ Panel = MicrophonePanel }: { Panel?: typeof MicrophonePanel }) {
  const { call, t } = useSession()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState('')
  const [test, setTest] = useState<{ mode: Mode; finger: number | null; run: number } | null>(null)

  useEffect(() => {
    let current = true
    void Promise.all([
      call<{ modalities: Modalities | null }>('me'), call<FusionMethod>('fusionMethod'),
      call<FaceMethod>('faceMethod'), call<VoiceMethod>('voiceMethod'),
    ]).then(([me, method, face, voice]) => {
      if (!current) return
      if (!me.ok) return setError(errorText(me, t))
      if (!method.ok) return setError(errorText(method, t))
      setLoaded({ method: method.data, modalities: me.data.modalities ?? {}, face: face.ok ? face.data : null,
        voice: voice.ok ? voice.data : null })
    })
    return () => { current = false }
    // The texts' language does not load the page again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call])

  if (error) return <section><h1>{t.fusion.name}</h1><Notice tone="alert" role="alert" still>{error}</Notice></section>
  if (loaded === null) return <section><h1>{t.fusion.name}</h1><p className="aside">{t.loading}</p></section>
  if (test === null) return <FusionChoice loaded={loaded} onStart={(mode, finger) => setTest({ mode, finger, run: Date.now() })} />
  const inTest = OTHERS.filter((name) => loaded.modalities[name]?.enrolled)
  return (
    <FusionTest key={test.run} mode={test.mode} finger={test.finger} inTest={inTest} face={loaded.face}
      voice={loaded.voice} Panel={Panel} onAgain={() => setTest({ ...test, run: Date.now() })} onLeave={() => setTest(null)} />
  )
}

function FusionChoice({ loaded, onStart }: { loaded: Loaded; onStart: (mode: Mode, finger: number | null) => void }) {
  const { t } = useSession()
  const navigate = useNavigate()
  const fu = t.fusion
  const fingers = loaded.modalities.fingerprint?.fingers ?? []
  const others = OTHERS.filter((name) => loaded.modalities[name]?.enrolled)
  const [finger, setFinger] = useState<number | null>(fingers[0] ?? null)
  const ready = fingers.length > 0 && others.length > 0
  const { weights, calibration } = loaded.method.policy
  const pages: Record<FusionModality, string> = { fingerprint: '/fingerprint', face: '/face', voice: '/voice' }
  return (
    <section className="fusion-choice">
      <div className="fusion-head">
        <h1>{fu.name}</h1>
        <p className="lead">{fu.lead}</p>
      </div>
      <ul className="points-list">
        {FUSION_MODALITIES.map((modality) => {
          const enrolled = modality === 'fingerprint' ? fingers.length > 0 : others.includes(modality)
          return (
            <li key={modality} data-enrolled={enrolled}>
              <span className="points-list__weight"><b>{weights[modality]}</b><span>{fu.points}</span></span>
              <span className="points-list__text">
                <strong>{t.modalities[modality]}{calibration[modality].provisional && <> <Tag>{fu.provisional}</Tag></>}</strong>
                <span>{enrolled ? fu.how[modality] : fu.notInTest}</span>
              </span>
            </li>
          )
        })}
      </ul>
      <p className="fusion-rule">{fu.rule}</p>
      {ready ? (
        <>
          <fieldset className="finger-choice">
            <legend>{fu.finger}</legend>
            {fingers.map((position) => (
              <label key={position}>
                <input type="radio" name="fusion-finger" checked={finger === position} onChange={() => setFinger(position)} />
                <span>{t.fingerprint.fingers[position]}</span>
              </label>
            ))}
          </fieldset>
          <div className="actions">
            <button type="button" className="primary" disabled={finger === null} onClick={() => onStart('verify', finger)}>{fu.verify}</button>
            <button type="button" onClick={() => onStart('identify', null)}>{fu.identify}</button>
            <button type="button" className="quiet" onClick={() => navigate('/')}>{fu.back}</button>
          </div>
        </>
      ) : (
        <>
          <Notice role="status" still>{fu.needs}</Notice>
          <div className="actions">
            {FUSION_MODALITIES.filter((m) => (m === 'fingerprint' ? fingers.length === 0 : !others.includes(m))).map((m) => (
              <button key={m} type="button" onClick={() => navigate(pages[m])}>{fu.enrol[m]}</button>
            ))}
            <button type="button" className="quiet" onClick={() => navigate('/')}>{fu.back}</button>
          </div>
        </>
      )}
    </section>
  )
}

type Step = 'face' | 'voice' | 'fingerprint' | 'result'
type Refusal = { modality: 'face' | 'voice'; checks: Array<FaceCheck | VoiceCheck> }

function timeOf(at: string, t: Texts): string {
  return new Date(at).toLocaleTimeString(t.dateLocale, { hour: '2-digit', minute: '2-digit' })
}

function FusionTest({ mode, finger, inTest, face, voice, Panel, onAgain, onLeave }: {
  mode: Mode
  finger: number | null
  inTest: Array<'face' | 'voice'>
  face: FaceMethod | null
  voice: VoiceMethod | null
  Panel: typeof MicrophonePanel
  onAgain: () => void
  onLeave: () => void
}) {
  const { call, t } = useSession()
  const fu = t.fusion
  const steps: Step[] = [...inTest, 'fingerprint', 'result']
  const [step, setStep] = useState<Step>(steps[0]!)
  const [samples, setSamples] = useState<FusionSamples>({})
  const [checking, setChecking] = useState(false)
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const [failure, setFailure] = useState('')
  const [result, setResult] = useState<{ answer: FusionResult; image: string } | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [step])

  const next = (after: Step) => setStep(steps[steps.indexOf(after) + 1]!)

  async function checkFace(image: string) {
    setRefusal(null)
    setFailure('')
    setChecking(true)
    const answer = await call<FaceCheckResult>('checkFace', { image })
    setChecking(false)
    if (!answer.ok) return setFailure(fu.errors[answer.error] ?? errorText(answer, t))
    if (!answer.data.passed) return setRefusal({ modality: 'face', checks: answer.data.checks })
    setSamples((current) => ({ ...current, face: { image, captured_at: new Date().toISOString() } }))
    next('face')
  }

  async function checkVoice(recorded: Recorded) {
    setRefusal(null)
    setFailure('')
    setChecking(true)
    const answer = await call<VoiceCheckResult>('checkVoice', { recording: recorded.recording })
    setChecking(false)
    if (!answer.ok) return setFailure(fu.errors[answer.error] ?? errorText(answer, t))
    if (!answer.data.passed) return setRefusal({ modality: 'voice', checks: answer.data.checks })
    setSamples((current) => ({ ...current, voice: { recording: recorded.recording, captured_at: recorded.capturedAt } }))
    next('voice')
  }

  if (step === 'result' && result !== null)
    return <FusionResultView mode={mode} result={result.answer} image={result.image} onAgain={onAgain} onLeave={onLeave} />

  const current = steps.indexOf(step)
  const sentence = t.voice.sentences[t.voice.sentences.length - 1]!
  return (
    <section className={`fusion-test fusion-${step}`}>
      <div className="fusion-column">
        <p className="aside">{fu.pre[mode]}</p>
        <Steps label={fu.stepsLabel} steps={steps.map((name) => fu.steps[name]!)} current={current} reached={(index) => index < current} />
        {step === 'face' && (
          <>
            <h1 ref={heading} tabIndex={-1}>{fu.face.title}</h1>
            <p className="lead">{fu.face.lead}</p>
          </>
        )}
        {step === 'voice' && (
          <>
            <h1 ref={heading} tabIndex={-1}>{fu.voice.title}</h1>
            <p className="lead">{fu.voice.lead}</p>
          </>
        )}
        {step === 'fingerprint' && (
          <FusionScan mode={mode} finger={finger} samples={samples} heading={heading}
            onResult={(answer, image) => { setResult({ answer, image }); setStep('result') }}
            onSampleRefused={(modality) => {
              setFailure(fu.sampleRefused[modality] ?? '')
              setSamples((current) => {
                const kept = { ...current }
                delete kept[modality]
                return kept
              })
              setStep(modality)
            }} />
        )}
        {(Object.keys(samples) as Array<'face' | 'voice'>).filter((name) => samples[name]).length > 0 && step === 'fingerprint' && (
          <ul className="taken">
            {OTHERS.filter((name) => samples[name]).map((name) => (
              <li key={name}><Icon name="check" /><span>{fu.taken[name]!(timeOf(samples[name]!.captured_at, t))}</span></li>
            ))}
          </ul>
        )}
        {refusal && (
          <Notice tone="alert" className="rejected">
            <h2>{refusal.modality === 'face' ? fu.face.refused : fu.voice.refused}</h2>
            <ul className="checks">
              {refusal.checks.map((item) => (
                <li key={item.name} className={item.passed ? 'met' : 'missing'}>
                  <Icon name={item.passed ? 'check' : 'alert'} />
                  <span>{refusal.modality === 'face' ? faceCheckLine(item as FaceCheck, t) : voiceCheckLine(item as VoiceCheck, t)}</span>
                </li>
              ))}
            </ul>
          </Notice>
        )}
        {failure && <Notice tone="alert" role="alert">{failure}</Notice>}
        <div className="prompt" role="status" aria-live="polite">
          {checking && <Notice tone="busy">{step === 'face' ? fu.face.checking : fu.voice.checking}</Notice>}
        </div>
        {step !== 'fingerprint' && <button type="button" className="secondary" onClick={onLeave}>{fu.cancel}</button>}
      </div>
      {step === 'face' && face && (
        <div className="fusion-device">
          <CameraPanel busy={checking} minimumWidth={face.width_minimum} onTaken={(image) => void checkFace(image)} />
        </div>
      )}
      {step === 'voice' && voice && (
        <div className="fusion-device">
          <Panel busy={checking} seconds={voice.recording_seconds} rate={voice.sample_rate} sentence={sentence}
            onRecorded={(recorded: Recorded) => void checkVoice(recorded)} />
        </div>
      )}
      {(step === 'face' && !face) || (step === 'voice' && !voice) ? (
        <Notice tone="alert" role="alert">{fu.errors[`${step}_unavailable`]}</Notice>
      ) : null}
    </section>
  )
}

function FusionScan({ mode, finger, samples, heading, onResult, onSampleRefused }: {
  mode: Mode
  finger: number | null
  samples: FusionSamples
  heading: RefObject<HTMLHeadingElement | null>
  onResult: (answer: FusionResult, image: string) => void
  onSampleRefused: (modality: 'face' | 'voice') => void
}) {
  const { call, t } = useSession()
  const fu = t.fusion
  const [phase, setPhase] = useState('starting')
  const [rejection, setRejection] = useState('')
  const [image, setImage] = useState('')
  const [failure, setFailure] = useState('')
  const runId = useRef('')

  useEffect(() => {
    const id = crypto.randomUUID()
    runId.current = id
    let active = true
    let finished = false
    let started = false
    let captured = ''
    const stop = window.mbs.onFusion(id, (event: FusionEvent) => {
      if (!active || finished) return
      switch (event.type) {
        case 'place':
        case 'checking':
        case 'lift':
        case 'comparing':
        case 'searching':
        case 'saving':
          setPhase(event.type)
          break
        case 'rejected':
          setRejection(t.fingerprint.rejected(event.score, event.minimum))
          break
        case 'captured':
          captured = event.image
          setImage(event.image)
          setRejection('')
          break
        case 'sample_rejected':
          finished = true
          onSampleRefused(event.modality as 'face' | 'voice')
          break
        case 'verified':
        case 'identified':
          finished = true
          onResult(event, captured)
          break
        case 'failed':
          finished = true
          setPhase('failed')
          setFailure(fu.errors[event.error] ?? t.fingerprint.errors[event.error] ?? t.errors[event.error] ?? t.unexpected)
          break
      }
    })
    // As fingerprint verification: React's development check mounts the effect twice; the scan starts after it (H35).
    queueMicrotask(() => {
      if (!active) return
      started = true
      void window.mbs.fuse(mode, id, mode === 'verify' ? finger : null, samples).then((answer) => {
        if (!active || finished || answer.ok) return
        finished = true
        setPhase('failed')
        setFailure(fu.errors[answer.error] ?? errorText(answer, t))
        if (answer.status === 401) void call('me')
      })
    })
    return () => {
      active = false
      stop()
      if (started && !finished) window.mbs.cancelFusion(id)
    }
    // One scan for this step: a language or theme update must not start another.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const busy = phase === 'checking' || phase === 'comparing' || phase === 'searching' || phase === 'saving'
  const fingerName = finger === null ? '' : t.fingerprint.fingers[finger] ?? ''
  return (
    <>
      <h1 ref={heading} tabIndex={-1}>{finger === null ? fu.fingerprint.titleAny : fu.fingerprint.title(fingerName)}</h1>
      {phase === 'failed' ? (
        <>
          <Notice tone="alert" role="alert">{failure}</Notice>
        </>
      ) : (
        <>
          {(phase === 'place' || phase === 'starting') && <Notice tone="live" still>{fu.fingerprint.live}</Notice>}
          {phase === 'lift' && <Notice tone="live">{fu.fingerprint.lift}</Notice>}
          <p className="lead">{fu.fingerprint.lead}</p>
          {rejection && <Notice tone="alert">{rejection}</Notice>}
          <div className="prompt" role="status" aria-live="polite">
            {busy && <Notice tone="busy">{phase === 'checking' ? fu.fingerprint.checking
              : phase === 'searching' ? fu.fingerprint.searching : fu.fingerprint.computing}</Notice>}
          </div>
        </>
      )}
      {image && <Plate image={image} size={220} className="fusion-capture" />}
      <div className="actions">
        <button type="button" className="secondary" onClick={() => {
          if (runId.current) window.mbs.cancelFusion(runId.current)
        }} disabled={phase === 'failed' || phase === 'saving'}>{fu.cancel}</button>
      </div>
    </>
  )
}

function format(value: number, t: Texts, digits = 1): string {
  return value.toLocaleString(t.dateLocale, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function factorText(log10: number, t: Texts): string {
  const x = 10 ** log10
  const shown = x >= 1000 ? Number(x.toPrecision(2)) : x >= 10 ? Math.round(x) : Math.round(x * 10) / 10
  return shown.toLocaleString(t.dateLocale)
}

function FusionResultView({ mode, result, image, onAgain, onLeave }: {
  mode: Mode
  result: FusionResult
  image: string
  onAgain: () => void
  onLeave: () => void
}) {
  const { t } = useSession()
  const fu = t.fusion
  const r = fu.result
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [])
  const parts = Object.fromEntries(result.parts.map((part) => [part.modality, part]))
  const fingerprint = parts.fingerprint
  const identify = mode === 'identify'
  const verdict = identify
    ? result.accepted ? (result.leader?.own ? r.found : r.foundOther) : r.notFound
    : result.accepted ? r.accepted : r.rejected
  const others = result.parts.filter((part) => part.modality !== 'fingerprint')
  const rescued = !identify && result.accepted && fingerprint !== undefined && !fingerprint.accepted
  const unsupported = !identify && !result.accepted && fingerprint !== undefined && fingerprint.evidence <= 0
    && others.length > 0 && others.every((part) => part.evidence > 0)
  const candidates = result.candidates ?? []
  const explain = identify
    ? candidates.length > 1 ? r.leadN(result.people ?? candidates.length, format(candidates[1]!.score, t)) : r.leadAlone
    : (result.accepted ? r.explain : r.explainLow)(factorText(result.evidence, t))
  const starts = result.parts.map((_, index) => result.parts.slice(0, index).reduce((sum, part) => sum + part.points, 0))
  return (
    <section className={`fusion-result${result.accepted ? '' : ' not-accepted'}`}>
      <div className="fusion-result__head">
        <div className="fusion-result__verdict">
          <p className="aside">{fu.pre[mode]}{!identify && result.finger ? `, ${t.fingerprint.fingers[result.finger]}` : ''}</p>
          <h1 ref={heading} tabIndex={-1}>{verdict}</h1>
          <p className="lead">{explain}</p>
          {rescued && <p className="fusion-note">{r.rescued}</p>}
          {unsupported && <p className="fusion-note">{r.rejectedWhy}</p>}
          {identify && (result.tied_leaders ?? 1) > 1 && <p className="fusion-note">{r.tie}</p>}
        </div>
        <p className="fusion-result__figure"><span className="figure">{format(result.score, t)}</span><span>{r.score}</span></p>
      </div>
      <div className="stack-rail" style={{ '--at': result.threshold / 100 } as CSSProperties}>
        <div className="stack-rail__groove">
          {result.parts.map((part, index) => (
            <span key={part.modality} className="stack-rail__piece" data-modality={part.modality}
              style={{ '--from': starts[index]! / 100, '--size': part.points / 100 } as CSSProperties} />
          ))}
        </div>
        <div className="stack-rail__tick" />
        <div className="stack-rail__ends"><span>0</span><span className="stack-rail__at">{r.accept}</span><span>100</span></div>
      </div>
      <div className="fusion-result__body">
        {identify ? (
          <table className="ranking">
            <thead><tr>{r.headers.map((header, index) => <th key={index}>{header}</th>)}</tr></thead>
            <tbody>
              {candidates.map((candidate) => (
                <tr key={candidate.rank} className={candidate.own ? 'own' : undefined}>
                  <td>{candidate.rank}</td>
                  <td>{candidate.own ? <>{r.you}{candidate.finger ? <span className="ranking__sub">{t.fingerprint.fingers[candidate.finger]}</span> : null}</> : r.other}</td>
                  {FUSION_MODALITIES.map((m) => <td key={m}>{candidate.points[m] === undefined ? '' : format(candidate.points[m]!, t)}</td>)}
                  <td><b>{format(candidate.score, t)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <ul className="contrib" aria-label={r.contributions}>
            {result.parts.map((part) => (
              <li key={part.modality} className="contrib__row" data-modality={part.modality}>
                <span className="contrib__name"><i aria-hidden="true" />{t.modalities[part.modality]}</span>
                <span className="contrib__pts"><b>{format(part.points, t)}</b> {r.of('', part.weight).trim()}</span>
                <span className="contrib__track" style={{ '--fill': part.points / part.weight } as CSSProperties}><span /></span>
                <span className="contrib__detail">
                  {r.own[part.modality]!(part.modality === 'fingerprint' ? format(part.score, t, 0) : format(part.score, t, 2), part.accepted)}
                  {' · '}{r.factor(factorText(part.evidence, t))}
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="fusion-plates">
          {result.parts.map((part) => (
            <figure key={part.modality}>
              {part.modality === 'fingerprint'
                ? (image ? <Plate image={image} size={128} /> : <div className="plate-empty" />)
                : <div className="ring-holder"><Ring values={part.values ?? []} size={128} /></div>}
              <figcaption><strong>{t.modalities[part.modality]}</strong><span>{r.of(format(part.points, t), part.weight)}</span></figcaption>
            </figure>
          ))}
        </div>
      </div>
      <div className="fusion-result__foot">
        <p className="aside">
          {r.duration} <b>{r.seconds(format(result.duration_ms / 1000, t, 2))}</b>
          {identify && result.people !== undefined ? <> · <b>{r.people(result.people)}</b></> : null}
          {' · '}{r.saved}
        </p>
        <div className="actions">
          <button type="button" className="primary" onClick={onAgain}>{r.again}</button>
          <button type="button" className="quiet" onClick={onLeave}>{r.back}</button>
        </div>
      </div>
    </section>
  )
}
