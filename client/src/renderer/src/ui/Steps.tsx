// Light Table's steps (H22): where a flow stands, on one line, a bar and a word per step. Reached steps are ink, the
// current one also names itself in ink; the bars change colour and nothing slides. The flow's own notice says what
// happens inside the current step.
export function Steps({ label, steps, current, reached }: {
  label: string
  steps: string[]
  /** The step under way, or -1 when the flow has ended or not started. */
  current: number
  reached: (index: number) => boolean
}) {
  return (
    <ol className="steps-rail" aria-label={label}>
      {steps.map((step, index) => (
        <li key={step} data-state={index === current ? 'current' : reached(index) ? 'done' : 'todo'}
          aria-current={index === current ? 'step' : undefined}>
          <span>{step}</span>
        </li>
      ))}
    </ol>
  )
}
