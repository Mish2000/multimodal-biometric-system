// H38, H42: one method catalog for verification and gallery identification, as Light Table's method cards (H22): the
// name, how the method works, then the two figures people choose by, accuracy and speed, and the threshold.
import type { FingerprintAlgorithm, FingerprintMethod } from '../../../shared/bridge'
import { useSession } from '../session'
import { Icon } from '../ui/Icon'
import { Notice } from '../ui/Notice'
import { Tag } from '../ui/Tag'

// True accepts at a 0.1% false-accept target in SD302 pair comparisons on other scanners (RxJ, and QxJ in the label),
// and the processing after a capture estimated from H10 on this computer: with three comparisons for verification,
// for the new template alone for identification, whose label adds the cost of each stored template.
const FIGURES: Record<FingerprintAlgorithm, { rxj: string; qxj: string; verification: string; identification: string }> = {
  'opencv-sift': { rxj: '70.8', qxj: '68.1', verification: '0.7', identification: '0.25' },
  'pore-sift': { rxj: '77.9', qxj: '78.5', verification: '3.2', identification: '3.1' },
  'learned-pore': { rxj: '95.1', qxj: '93.4', verification: '3.2', identification: '3.2' },
}

export function MethodChoices({ methods, algorithm, onChoose, error, onRetry, purpose = 'verification', compared = [] }: {
  methods: FingerprintMethod[]
  algorithm: FingerprintAlgorithm
  onChoose: (algorithm: FingerprintAlgorithm) => void
  error: string
  onRetry: () => void
  purpose?: 'verification' | 'identification'
  /** H59: the methods the shown capture was already compared with. */
  compared?: FingerprintAlgorithm[] | undefined
}) {
  const { t } = useSession()
  const f = t.fingerprint
  const identifying = purpose === 'identification'
  return (
    <fieldset className="method-choices">
      <legend>{identifying ? f.identification.methodChoice : f.methodChoice}</legend>
      {methods.map((method) => {
        const figures = FIGURES[method.code]
        return (
          <label key={method.code} className={method.available ? 'method-choice' : 'method-choice unavailable'}>
            <input type="radio" name="fingerprint-method" value={method.code} checked={algorithm === method.code}
              aria-labelledby={`method-${method.code}`} aria-describedby={`method-${method.code}-description`}
              disabled={!method.available} onChange={() => onChoose(method.code)} />
            <span className="method-head">
              <strong className="method-name" id={`method-${method.code}`}>{f.methodNames[method.code]}</strong>
              <span className="method-radio" aria-hidden="true" />
            </span>
            <span className="method-description" id={`method-${method.code}-description`}>{f.methodDescriptions[method.code]}</span>
            <span className="method-figures">
              <span className="figure">
                <span className="figure-value">{figures.rxj}<span className="figure-unit">%</span></span>
                <span className="figure-label">{f.figureAccuracy(figures.qxj)}</span>
              </span>
              <span className="figure">
                <span className="figure-value">
                  {identifying ? figures.identification : figures.verification}
                  {f.figureUnit && <span className="figure-unit">{f.figureUnit}</span>}
                </span>
                <span className="figure-label">{identifying ? f.identification.figureSpeed[method.code] : f.figureSpeed}</span>
              </span>
            </span>
            <span className="method-threshold">
              {f.verification.threshold(method.threshold)}
              {method.threshold_provisional && <Tag>{f.provisional}</Tag>}
              {compared.includes(method.code) && <Tag tone="ink">{f.capture.compared}</Tag>}
            </span>
            {!method.available && <span className="method-problem"><Icon name="alert" />{f.methodUnavailable}</span>}
          </label>
        )
      })}
      {methods.length > 0 && <p className="method-note">{identifying ? f.identification.figuresNote : f.figuresNote}</p>}
      {error ? (
        <div>
          <Notice tone="alert" role="alert">{error}</Notice>
          <button type="button" className="secondary" onClick={onRetry}>{f.tryAgain}</button>
        </div>
      ) : methods.length === 0 && <p className="aside">{t.loading}</p>}
    </fieldset>
  )
}
