// H38, H42: one method catalog for verification and gallery identification.
import type { FingerprintAlgorithm, FingerprintMethod } from '../../../shared/bridge'
import { useSession } from '../session'

export function MethodChoices({ methods, algorithm, onChoose, error, onRetry, purpose = 'verification' }: {
  methods: FingerprintMethod[]
  algorithm: FingerprintAlgorithm
  onChoose: (algorithm: FingerprintAlgorithm) => void
  error: string
  onRetry: () => void
  purpose?: 'verification' | 'identification'
}) {
  const { t } = useSession()
  const f = t.fingerprint
  const identifying = purpose === 'identification'
  const speed = identifying ? f.identification.methodSpeed : f.methodSpeed
  return (
    <fieldset className="method-choices">
      <legend>{identifying ? f.identification.methodChoice : f.methodChoice}</legend>
      {methods.map((method) => (
        <label key={method.code} className="method-choice">
          <input type="radio" name="fingerprint-method" value={method.code} checked={algorithm === method.code}
            aria-labelledby={`method-${method.code}`} aria-describedby={`method-${method.code}-description`}
            disabled={!method.available} onChange={() => onChoose(method.code)} />
          <span>
            <strong id={`method-${method.code}`}>{f.methodNames[method.code]}</strong>
            <span className="method-description" id={`method-${method.code}-description`}>{f.methodDescriptions[method.code]}</span>
            <span className="method-description aside">{f.methodAccuracy[method.code]}</span>
            <span className="method-description aside">{speed[method.code]}</span>
            <span className="method-description">{f.verification.threshold(method.threshold)}{method.threshold_provisional ? ` · ${f.provisional}` : ''}</span>
            {!method.available && <span className="method-description error">{f.methodUnavailable}</span>}
          </span>
        </label>
      ))}
      {error ? (
        <div>
          <p className="error" role="alert">{error}</p>
          <button type="button" className="secondary" onClick={onRetry}>{f.tryAgain}</button>
        </div>
      ) : methods.length === 0 && <p className="aside">{t.loading}</p>}
    </fieldset>
  )
}
