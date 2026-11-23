// H60: a face's or a voice's embedding as Light Table draws it (H22): one short line per value around a circle,
// outwards for a positive value and inwards for a negative one, its length by the value against the largest of
// them. Drawn in ink on a plate's light, so the dark theme shows its negative like the prints.
export function Ring({ values, size, label }: { values: number[]; size: number; label?: string }) {
  const middle = size / 2
  const radius = size * 0.29
  const longest = size * 0.17
  const largest = Math.max(...values.map((value) => Math.abs(value)), Number.EPSILON)
  const lines = values.map((value, index) => {
    const angle = (index / values.length) * 2 * Math.PI - Math.PI / 2
    const length = Math.max(size * 0.008, (Math.abs(value) / largest) * longest)
    const end = radius + (value >= 0 ? length : -length)
    const [cos, sin] = [Math.cos(angle), Math.sin(angle)]
    return `M${(middle + radius * cos).toFixed(1)} ${(middle + radius * sin).toFixed(1)}L${(middle + end * cos).toFixed(1)} ${(middle + end * sin).toFixed(1)}`
  })
  return (
    <svg className="ring-plate" width={size} height={size} viewBox={`0 0 ${size} ${size}`}
      role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={lines.join('')} />
    </svg>
  )
}
