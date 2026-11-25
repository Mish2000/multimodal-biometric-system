// H62: the administration area's reports, one per method and one for the combined test (H60), as their key screens
// were approved (version 2, 2026-11-25): in the user screens' language, built as the combined test's result is. The
// six reports are listed beside the chosen one, whose head is a context line, the report's name as the headline, its
// threshold and where it comes from as the lead, and the attempts above it as one light figure; the scores lie on the
// results' rail with the threshold's labelled tick; the figures follow without frames. Sums only, counted by the
// server in one snapshot, under the history's filters; each report leads to the history's same attempts. The page
// stays still.
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import type { Report, ReportBar, ReportCode, ReportDates, ReportFilters, ReportRange, ReportsAnswer } from '../../../shared/bridge'
import { useSession } from '../session'
import { errorText, type Texts } from '../texts'
import { Icon } from '../ui/Icon'
import { Notice } from '../ui/Notice'
import { Tag } from '../ui/Tag'
import { FilterPill, type Choice } from './FilterPill'
import { METHODS, withRatios, type HistoryPreset } from './History'
import { DaysStrip, ScoresChart, counted, type LegendItem } from './ReportCharts'

type Mode = 'verify' | 'identify'
interface Chosen {
  dates: ReportDates | null
  mode: Mode | null
  source: 'device' | 'file' | null
}
const NONE: Chosen = { dates: null, mode: null, source: null }
const GROUPS = [
  ['fingerprint', ['opencv-sift', 'pore-sift', 'learned-pore']],
  ['face', ['sface']],
  ['voice', ['ecapa-voxceleb']],
  ['combined', ['combined']],
] as const
const MODALITIES = ['fingerprint', 'face', 'voice'] as const
const DAY_MS = 86_400_000

function filtersOf(chosen: Chosen, zone: string): ReportFilters {
  const filters: ReportFilters = { zone }
  if (chosen.dates !== null) filters.dates = chosen.dates
  if (chosen.mode !== null) filters.mode = chosen.mode
  if (chosen.source !== null) filters.source = chosen.source
  return filters
}

// Numbers as the result screens write them.
function numbers(t: Texts) {
  const locale = t.dateLocale
  return {
    int: (n: number) => Math.round(n).toLocaleString(locale),
    plain: (n: number) => n.toLocaleString(locale, { maximumFractionDigits: 3 }),
    seconds: (ms: number) => (ms / 1000).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    factor: (x: number) => Number(x.toPrecision(2)).toLocaleString(locale),
  }
}

// The server's days are the PC's calendar days; written at noon UTC they keep their date in any zone.
const noon = (day: string) => Date.parse(`${day}T12:00:00Z`)
const after = (day: string, days: number) => new Date(noon(day) + days * DAY_MS)
const dayText = (at: Date, t: Texts, month: 'long' | 'short', year = false) =>
  at.toLocaleDateString(t.dateLocale, { day: 'numeric', month, ...(year ? { year: 'numeric' } : {}), timeZone: 'UTC' })

// "6 to 24 November 2026": the month and the year are named once when both days share them.
function rangeText(range: ReportRange, t: Texts): string {
  const last = dayText(after(range.to, 0), t, 'long', true)
  if (range.from === range.to) return last
  const first = range.from.slice(0, 7) === range.to.slice(0, 7)
    ? after(range.from, 0).getUTCDate().toLocaleString(t.dateLocale)
    : dayText(after(range.from, 0), t, 'long', range.from.slice(0, 4) !== range.to.slice(0, 4))
  return t.reports.range(first, last)
}

const thresholdText = (report: Report, t: Texts) =>
  report.scale === 'pairs' ? numbers(t).int(report.threshold) : numbers(t).plain(report.threshold)
const aboveOf = (report: Report) => report.verify.accepted + report.identify.accepted

export function Reports() {
  const { call, t } = useSession()
  const r = t.reports
  const h = t.history
  const navigate = useNavigate()
  const [chosen, setChosen] = useState<Chosen>(NONE)
  const [code, setCode] = useState<ReportCode>('opencv-sift')
  const [answer, setAnswer] = useState<ReportsAnswer | null>(null)
  const [answered, setAnswered] = useState<ReportFilters | null>(null) // the filters the reports shown answer
  const [error, setError] = useState<Parameters<typeof errorText>[0] | null>(null)
  const asked = useRef(0)
  // The PC's own time zone: the server starts each day at its midnight, as the history's dates do.
  const [zone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone)
  const filters = useMemo(() => filtersOf(chosen, zone), [chosen, zone])

  // Each change of the filters asks again; an older answer that arrives later is dropped.
  useEffect(() => {
    const ask = ++asked.current
    void call<ReportsAnswer>('reports', filters).then((reply) => {
      if (ask !== asked.current) return
      setAnswered(filters)
      if (reply.ok) {
        setAnswer(reply.data)
        setError(null)
      } else setError(reply)
    })
  }, [call, filters])
  // Reports that answer other filters than the ones shown are marked busy until the new answer comes.
  const busy = answered !== filters

  const any = Object.values(chosen).some((value) => value !== null)
  const pick = <K extends keyof Chosen>(key: K) => (value: Chosen[K]) => setChosen((before) => ({ ...before, [key]: value }))
  const choices = <V extends string>(values: readonly V[], label: (value: V) => ReactNode): Array<Choice<V>> =>
    values.map((value) => ({ value, label: label(value) }))
  const report = answer?.reports.find((found) => found.code === code)
  const fingerprint = answer?.reports.find((found) => found.code === 'opencv-sift')

  // The history with the same filters lists exactly the attempts this report counts.
  function showInHistory(shown: Report) {
    const preset: HistoryPreset = {
      dates: chosen.dates,
      mode: chosen.mode,
      source: chosen.source,
      type: shown.code === 'combined' ? 'combined' : shown.modality,
      method: shown.code === 'combined' ? null : shown.code,
    }
    void navigate('/admin/history', { state: { preset } })
  }

  return (
    <div className="reports-page">
      <div className="filters" role="group" aria-label={h.filters}>
        <FilterPill name={r.filter.dates} value={chosen.dates} shown={chosen.dates && r.dates[chosen.dates]} removeLabel={h.remove}
          choices={choices(['today', 'week', 'month'] as const, (value) => r.dates[value])} onChange={pick('dates')} />
        <FilterPill name={r.filter.mode} value={chosen.mode} shown={chosen.mode && withRatios(r.modes[chosen.mode])} removeLabel={h.remove}
          choices={choices(['verify', 'identify'] as const, (value) => withRatios(r.modes[value]))} onChange={pick('mode')} />
        <FilterPill name={r.filter.source} value={chosen.source} shown={chosen.source && r.sourceSet(r.sources[chosen.source])} removeLabel={h.remove}
          choices={choices(['device', 'file'] as const, (value) => r.sources[value])} onChange={pick('source')} />
        {any && (
          <button type="button" className="quiet small filters__clear" onClick={() => setChosen(NONE)}>
            {h.clear}
          </button>
        )}
        {/* Without dates the range starts at the system's first attempt; before any attempt there is none to name. */}
        {answer !== null && (chosen.dates !== null || answer.reports.some((each) => each.n > 0)) && (
          <span className="filters__range">{chosen.dates ? rangeText(answer.range, t) : r.since(rangeText(answer.range, t))}</span>
        )}
      </div>
      {error && (
        <Notice tone="alert" role="alert">
          {errorText(error, t)}
        </Notice>
      )}
      {answer === null ? (
        !error && <p className="aside">{t.loading}</p>
      ) : (
        <div className="reports" aria-busy={busy}>
          <nav className="report-list" aria-label={r.list}>
            {GROUPS.map(([group, codes]) => (
              <Fragment key={group}>
                <p className="report-list__group">{r.kinds[group]}</p>
                {codes.map((listed) => {
                  const item = answer.reports.find((found) => found.code === listed)
                  return item === undefined ? null : (
                    <ListItem key={listed} report={item} current={listed === code} onChoose={() => setCode(listed)} />
                  )
                })}
              </Fragment>
            ))}
          </nav>
          {report !== undefined && (
            <ReportView
              key={report.code}
              report={report}
              range={answer.range}
              mode={chosen.mode}
              filtered={any}
              fingerprintThreshold={fingerprint?.threshold}
              onClear={() => setChosen(NONE)}
              onShow={showInHistory}
            />
          )}
        </div>
      )}
    </div>
  )
}

// A report in the list: its name, its attempts, and the share of them above its threshold.
function ListItem({ report, current, onChoose }: { report: Report; current: boolean; onChoose(): void }) {
  const { t } = useSession()
  const share = report.n > 0 ? aboveOf(report) / report.n : 0
  const combined = report.code === 'combined'
  const name = combined ? t.reports.combined : METHODS[report.code]
  const count = numbers(t).int(report.n)
  return (
    <button type="button" className="report-list__item" aria-current={current ? 'true' : undefined} onClick={onChoose}
      aria-label={t.reports.listItem(name, report.n, count, combined)}>
      <span className="report-list__name">{combined ? name : <span className="latin">{name}</span>}</span>
      <span className="report-list__count">{count}</span>
      <span className="report-list__share" aria-hidden="true">
        <i style={{ '--a': share.toFixed(4) } as CSSProperties} />
      </span>
    </button>
  )
}

// The head, as a result's: a context line, the report's name as the headline, its threshold and where it comes from.
function ReportHead({ report }: { report: Report }) {
  const { t } = useSession()
  const r = t.reports
  const n = numbers(t)
  let lead: string
  let tag: ReactNode = null
  if (report.code === 'combined') {
    const policy = report.policy
    const weights = MODALITIES.map((modality) => String(policy.weights[modality]))
    const ratio = 10 ** (((policy.threshold - 50) * policy.budget) / 50)
    lead = r.combinedLead(n.plain(policy.threshold), policy.id,
      `${weights.slice(0, -1).join(', ')}${t.history.parts.and}${weights.at(-1)}`, n.factor(ratio))
    if (policy.provisional.length > 0) tag = <Tag>{r.scalesProvisional(policy.provisional)}</Tag>
  } else {
    lead = r.lead[report.code](thresholdText(report, t))
    if (report.provisional) tag = <Tag>{r.provisional}</Tag>
  }
  return (
    <div className="report-head__text">
      <p className="aside">{r.pre(r.kinds[report.modality])}</p>
      <h1 id="report-name">{report.code === 'combined' ? r.combined : <span className="latin">{METHODS[report.code]}</span>}</h1>
      <p className="lead report-head__lead">
        <span>{lead}</span>
        {tag}
      </p>
    </div>
  )
}

function ReportView({ report, range, mode, filtered, fingerprintThreshold, onClear, onShow }: {
  report: Report
  range: ReportRange
  mode: Mode | null
  filtered: boolean
  fingerprintThreshold: number | undefined
  onClear(): void
  onShow(report: Report): void
}) {
  const { t } = useSession()
  const r = t.reports
  const n = numbers(t)
  const combined = report.code === 'combined'

  if (report.n === 0) {
    return (
      <section className="report report--empty" aria-labelledby="report-name">
        <ReportHead report={report} />
        <div className="report-empty">
          <h2>{filtered ? r.empty.title : r.none.title}</h2>
          <p>{filtered ? r.empty.text : combined ? r.none.combined : r.none.method}</p>
          {filtered && (
            <button type="button" className="small" onClick={onClear}>
              {t.history.clear}
            </button>
          )}
        </div>
      </section>
    )
  }

  const scale = report.scale
  const shownThreshold = thresholdText(report, t)
  // A bar's range in words: pairs are whole numbers, so (28, 57] is "29 to 57"; the first bar holds all below it.
  const rangeOf = (bar: ReportBar) => {
    if (scale === 'pairs') return r.bar.pairs(n.int(Math.floor(bar.low) + 1), n.int(Math.floor(bar.high)))
    return bar.k === report.bars[0]?.k ? r.bar.upTo(n.plain(bar.high)) : r.bar.between(n.plain(bar.low), n.plain(bar.high))
  }
  const readout = (bar: ReportBar) => {
    const parts = [
      bar.accepted > 0 ? r.bar.above(n.int(bar.accepted), bar.other > 0 ? n.int(bar.other) : null) : '',
      bar.rejected > 0 ? r.bar.below(n.int(bar.rejected)) : '',
    ].filter(Boolean)
    return (
      <>
        <b>{rangeOf(bar)}</b>: {parts.length > 0 ? parts.join(', ') : r.bar.empty}
      </>
    )
  }
  const legend: LegendItem[] = [
    { key: 'above', label: r.legend.above },
    ...(report.bars.some((bar) => bar.other > 0) ? [{ key: 'other' as const, label: r.legend.other }] : []),
    { key: 'below', label: r.legend.below },
  ]

  // The strip of days: its title, its ends, and its busiest day in words.
  const unit = range.unit
  const ends: [string, string] = unit === 'hour'
    ? ['00:00', '23:00']
    : [dayText(after(range.from, 0), t, 'short'), dayText(after(range.to, 0), t, 'short')]
  const busiest = report.slots.reduce((best, slot, index) => (counted(slot) > counted(report.slots[best]!) ? index : best), 0)
  const most = report.slots[busiest] === undefined ? 0 : counted(report.slots[busiest])
  const when = unit === 'hour'
    ? r.atHour(`${String(busiest).padStart(2, '0')}:00`)
    : unit === 'day'
      ? r.onDay(dayText(after(range.from, busiest), t, 'long'))
      : r.inWeek(dayText(after(range.from, busiest * 7), t, 'long'))

  // Attempts decided by an earlier threshold or policy keep their own decision; one line says how many.
  let earlier: string | null = null
  const before = report.earlier.reduce((sum, entry) => sum + entry.n, 0)
  if (before > 0) {
    earlier = report.code === 'combined'
      ? r.earlierPolicy(before, n.int(before), report.earlier.map((entry) => r.policyName(entry.policy, n.plain(entry.threshold))).join('; '))
      : r.earlier(before, n.int(before), report.earlier.map((entry) => n.plain(entry.threshold)).join(', '))
  }

  return (
    <section className="report" aria-labelledby="report-name">
      <ReportHead report={report} />
      <div className="report-head__figure">
        <p className="report-head__value">
          <span className="figure-value">{n.int(aboveOf(report))}</span> <span className="figure-unit">{r.fig.of(n.int(report.n))}</span>
        </p>
        <p className="figure-label">{combined ? r.fig.testsAbove(shownThreshold) : r.fig.above}</p>
      </div>
      <DaysStrip
        slots={report.slots}
        title={r.per[unit][combined ? 'tests' : 'attempts']}
        ends={ends}
        locale={t.dateLocale}
        describe={most > 0 ? r.busiest(n.int(most), when) : null}
      />
      <ScoresChart
        bars={report.bars}
        scale={scale}
        threshold={report.threshold}
        wide={combined}
        at={r.at[scale](shownThreshold)}
        locale={t.dateLocale}
        caption={`${r.scores}, ${r.unit[scale]}`}
        hint={r.hint}
        legend={legend}
        readout={readout}
      />
      <Figures report={report} mode={mode} fingerprintThreshold={fingerprintThreshold} />
      <div className="report__foot">
        <div className="report__notes">
          {earlier !== null && <p className="report__note">{earlier}</p>}
          <p className="report__note">{combined ? r.combinedNote : r.note}</p>
        </div>
        <button type="button" className="small" onClick={() => onShow(report)}>
          {r.show(n.int(report.n))}
        </button>
      </div>
    </section>
  )
}

// Under the rail, as the result's modalities are: each mode's decisions with its time, then for the combined test
// where it overruled the fingerprint alone. Light figures without frames; a line breaks only between its parts.
function Figures({ report, mode, fingerprintThreshold }: { report: Report; mode: Mode | null; fingerprintThreshold: number | undefined }) {
  const { t } = useSession()
  const f = t.reports.fig
  const n = numbers(t)
  const combined = report.code === 'combined'
  const modes = (['verify', 'identify'] as const).filter((each) => mode === null || mode === each)
  const line = (parts: ReactNode[]) => {
    const shown = parts.filter((part) => part !== null && part !== '')
    return shown.length === 0 ? null : (
      <p className="rfig__sub">
        {shown.map((part, index) => (
          <Fragment key={index}>
            {index > 0 && ' · '}
            <span className="nowrap">{part}</span>
          </Fragment>
        ))}
      </p>
    )
  }
  return (
    <div className="report__figures">
      {modes.map((each) => {
        const x = report[each]
        if (x.n === 0) {
          return (
            <div key={each} className="rfig rfig--none">
              <p className="rfig__sub">{withRatios(f.none[each])}</p>
            </div>
          )
        }
        const time = [x.median_ms === null ? null : f.median(n.seconds(x.median_ms)), x.p90_ms === null ? null : f.p90(n.seconds(x.p90_ms))]
        const label = each === 'verify' ? (combined ? f.testsAccepted : f.accepted) : combined ? f.testsFound : f.found
        return (
          <div key={each} className="rfig">
            <p className="rfig__value">
              <span className="figure-value">{n.int(x.accepted)}</span> <span className="figure-unit">{f.of(n.int(x.n))}</span>
            </p>
            <p className="rfig__label">{withRatios(label)}</p>
            {line([each === 'verify' ? f.rejected(x.rejected, n.int(x.rejected)) : f.notFound(x.rejected, n.int(x.rejected)), ...time])}
            {each === 'identify' && line([
              x.own > 0 ? f.own(n.int(x.own)) : null,
              x.other > 0 ? <span key="other" className="leader--alert"><Icon name="alert" />{f.other(n.int(x.other))}</span> : null,
              x.gone > 0 ? f.gone(n.int(x.gone)) : null,
            ])}
          </div>
        )
      })}
      {combined && fingerprintThreshold !== undefined && (['rescued', 'stopped'] as const).map((key) => (
        <div key={key} className="rfig">
          <p className="rfig__value">
            <span className="figure-value">{n.int((report.verify[key] ?? 0) + (report.identify[key] ?? 0))}</span>
          </p>
          <p className="rfig__label">{f[key]}</p>
          <p className="rfig__sub">{(key === 'rescued' ? f.rescuedText : f.stoppedText)(n.int(fingerprintThreshold))}</p>
        </div>
      ))}
    </div>
  )
}
