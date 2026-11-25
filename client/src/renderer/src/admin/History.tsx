// H61: the administration area's attempt history. Every comparison by every user, newest first, 50 at a time, under
// filter pills; a combined test (H60) is one row that opens to its comparisons. Outcomes only: no image, recording,
// template or ID number, and the leader of a 1:N search is never named. The page stays still: the list scrolls in
// its panel under a header that stays.
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import type { HistoryCombined, HistoryFilters, HistoryPage, HistoryRow } from '../../../shared/bridge'
import { useSession } from '../session'
import { errorText, type Texts } from '../texts'
import { Icon } from '../ui/Icon'
import { Notice } from '../ui/Notice'
import { Tag } from '../ui/Tag'
import { FilterPill, type Choice } from './FilterPill'

export const METHODS = {
  'opencv-sift': 'OpenCV SIFT',
  'pore-sift': 'Pore SIFT',
  'learned-pore': 'Pore CNN',
  sface: 'SFace',
  'ecapa-voxceleb': 'ECAPA-TDNN',
} as const
type Method = keyof typeof METHODS
const MODALITIES = ['fingerprint', 'face', 'voice'] as const
const TYPES = [...MODALITIES, 'combined'] as const
type Dates = 'today' | 'week' | 'month'
const DAYS_BACK: Record<Dates, number> = { today: 0, week: 6, month: 29 }

interface Chosen {
  dates: Dates | null
  type: (typeof TYPES)[number] | null
  mode: 'verify' | 'identify' | null
  method: Method | null
  result: 'accepted' | 'rejected' | null
  source: 'device' | 'file' | null
}
const NONE: Chosen = { dates: null, type: null, mode: null, method: null, result: null, source: null }

// H62: a report opens the history with its own filters, so the history lists the very attempts it counted.
export type HistoryPreset = Partial<Chosen>
const ALLOWED: { [K in keyof Chosen]: readonly string[] } = {
  dates: Object.keys(DAYS_BACK),
  type: TYPES,
  mode: ['verify', 'identify'],
  method: Object.keys(METHODS),
  result: ['accepted', 'rejected'],
  source: ['device', 'file'],
}
function presetOf(state: unknown): Chosen {
  const preset = (state as { preset?: Record<string, unknown> } | null)?.preset
  const chosen: Record<string, unknown> = { ...NONE }
  if (preset !== undefined && preset !== null && typeof preset === 'object') {
    for (const key of Object.keys(NONE) as Array<keyof Chosen>) {
      const value = preset[key]
      if (typeof value === 'string' && ALLOWED[key].includes(value)) chosen[key] = value
    }
  }
  return chosen as unknown as Chosen
}

// Ratios such as 1:1 and 1:N keep their order inside Hebrew.
export function withRatios(text: string): ReactNode {
  return text.split(/(\d:[\dN])/).map((piece, index) => (index % 2 === 1 ? <bdi key={index}>{piece}</bdi> : piece))
}

function filtersOf(chosen: Chosen, user: string): HistoryFilters {
  const filters: HistoryFilters = {}
  if (chosen.dates !== null) {
    const day = new Date()
    day.setHours(0, 0, 0, 0)
    day.setDate(day.getDate() - DAYS_BACK[chosen.dates])
    filters.since = day.toISOString()
  }
  if (user) filters.user = user
  if (chosen.type !== null) filters.type = chosen.type
  if (chosen.mode !== null) filters.mode = chosen.mode
  if (chosen.method !== null) filters.method = chosen.method
  if (chosen.result !== null) filters.result = chosen.result
  if (chosen.source !== null) filters.source = chosen.source
  return filters
}

const fixed = (value: number, digits: number, t: Texts) =>
  value.toLocaleString(t.dateLocale, { minimumFractionDigits: digits, maximumFractionDigits: digits })
const plain = (value: number, t: Texts) => value.toLocaleString(t.dateLocale, { maximumFractionDigits: 3 })
const time = (iso: string, t: Texts) => new Date(iso).toLocaleTimeString(t.dateLocale, { hour: '2-digit', minute: '2-digit' })
const methodName = (code: string) => METHODS[code as Method] ?? code

// A likelihood ratio as people read it: two figures from a thousand, whole from ten, one decimal below.
function factor(x: number, t: Texts): string {
  const shown = x >= 1000 ? Number(x.toPrecision(2)) : x >= 10 ? Math.round(x) : x >= 1 ? Math.round(x * 10) / 10 : Number(x.toPrecision(2))
  return shown.toLocaleString(t.dateLocale)
}

function scoreOf(row: HistoryRow, t: Texts): string {
  if (row.kind === 'combined') return fixed(row.score, 1, t)
  return row.modality === 'fingerprint' ? fixed(row.score, 0, t) : fixed(row.score, 3, t)
}

function originOf(row: HistoryRow, t: Texts): string {
  const names = t.history.origin
  if (row.kind === 'combined') return names.devices
  if (row.source === 'file') return row.modality === 'face' ? names.image : names.recording
  return row.modality === 'fingerprint' ? names.scanner : row.modality === 'face' ? names.camera : names.microphone
}

function dayOf(iso: string, t: Texts): { key: string; label: string } {
  const day = new Date(iso)
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)
  const date = day.toLocaleDateString(t.dateLocale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  const label =
    day.toDateString() === today.toDateString()
      ? `${t.history.today}, ${date}`
      : day.toDateString() === yesterday.toDateString()
        ? `${t.history.yesterday}, ${date}`
        : date
  return { key: day.toDateString(), label }
}

export function AttemptHistory() {
  const { call, t } = useSession()
  const h = t.history
  const location = useLocation()
  const [chosen, setChosen] = useState<Chosen>(() => presetOf(location.state))
  const [user, setUser] = useState('')
  const [userQuery, setUserQuery] = useState('')
  const [page, setPage] = useState<HistoryPage | null>(null)
  const [answered, setAnswered] = useState<HistoryFilters | null>(null) // the filters the rows shown answer
  const [more, setMore] = useState(false)
  const [error, setError] = useState<Parameters<typeof errorText>[0] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const asked = useRef(0)
  const filters = useMemo(() => filtersOf(chosen, userQuery), [chosen, userQuery])

  // The user's name is searched once typing pauses.
  useEffect(() => {
    const timer = window.setTimeout(() => setUserQuery(user.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [user])

  // Each change of the filters reads the first page again; an older answer that arrives later is dropped.
  useEffect(() => {
    const ask = ++asked.current
    void call<HistoryPage>('attempts', filters).then((answer) => {
      if (ask !== asked.current) return
      setMore(false)
      setAnswered(filters)
      if (answer.ok) {
        setPage(answer.data)
        setError(null)
        setOpen(null)
      } else setError(answer)
    })
  }, [call, filters])
  // Rows that answer other filters than the ones shown are marked busy until the new answer comes.
  const busy = answered !== filters

  // An opened combined test comes into view just enough to show its comparisons.
  useEffect(() => {
    if (open !== null) document.getElementById(`parts-${open}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open])

  function showMore() {
    if (page?.next == null) return
    const ask = asked.current
    setMore(true)
    void call<HistoryPage>('attempts', { ...filters, after: page.next }).then((answer) => {
      if (ask !== asked.current) return
      setMore(false)
      if (answer.ok)
        setPage((before) => before && { rows: [...before.rows, ...answer.data.rows], total: answer.data.total, next: answer.data.next })
      else setError(answer)
    })
  }

  const any = Object.values(chosen).some((value) => value !== null) || user !== ''
  function clear() {
    setChosen(NONE)
    setUser('')
    setUserQuery('')
  }
  const pick = <K extends keyof Chosen>(key: K) => (value: Chosen[K]) => setChosen((before) => ({ ...before, [key]: value }))
  const choices = <V extends string>(values: readonly V[], label: (value: V) => ReactNode): Array<Choice<V>> =>
    values.map((value) => ({ value, label: label(value) }))

  const groups: Array<{ key: string; label: string; rows: HistoryRow[] }> = []
  for (const row of page?.rows ?? []) {
    const day = dayOf(row.at, t)
    if (groups.at(-1)?.key !== day.key) groups.push({ ...day, rows: [] })
    groups.at(-1)?.rows.push(row)
  }

  return (
    <div className="history">
      <div className="admin-head">
        <h1>{h.title}</h1>
        <p className="lead">{h.lead}</p>
      </div>
      <div className="filters" role="group" aria-label={h.filters}>
        <div className={`filter-search${user ? ' filter-search--set' : ''}`}>
          <Icon name="search" />
          <input value={user} onChange={(event) => setUser(event.target.value)} placeholder={h.user} aria-label={h.user} dir="auto" maxLength={32} />
          {user && (
            <button type="button" className="filter__remove" aria-label={h.clearUser} onClick={() => setUser('')}>
              <Icon name="close" />
            </button>
          )}
        </div>
        <FilterPill name={h.filter.dates} value={chosen.dates} shown={chosen.dates && h.dates[chosen.dates]} removeLabel={h.remove}
          choices={choices(['today', 'week', 'month'] as const, (value) => h.dates[value])} onChange={pick('dates')} />
        <FilterPill name={h.filter.type} value={chosen.type} shown={chosen.type && h.set(h.filter.type, h.types[chosen.type])} removeLabel={h.remove}
          choices={choices(TYPES, (value) => h.types[value])} onChange={pick('type')} />
        <FilterPill name={h.filter.mode} value={chosen.mode} shown={chosen.mode && withRatios(h.modes[chosen.mode])} removeLabel={h.remove}
          choices={choices(['verify', 'identify'] as const, (value) => withRatios(h.modes[value]))} onChange={pick('mode')} />
        <FilterPill name={h.filter.method} value={chosen.method} shown={chosen.method && h.set(h.filter.method, METHODS[chosen.method])} removeLabel={h.remove}
          choices={choices(Object.keys(METHODS) as Method[], (value) => <span className="latin">{METHODS[value]}</span>)} onChange={pick('method')} />
        <FilterPill name={h.filter.result} value={chosen.result} shown={chosen.result && h.set(h.filter.result, h.resultsShort[chosen.result])} removeLabel={h.remove}
          choices={choices(['accepted', 'rejected'] as const, (value) => h.results[value])} onChange={pick('result')} />
        <FilterPill name={h.filter.source} value={chosen.source} shown={chosen.source && h.set(h.filter.source, h.sources[chosen.source])} removeLabel={h.remove}
          choices={choices(['device', 'file'] as const, (value) => h.sources[value])} onChange={pick('source')} />
        {any && (
          <button type="button" className="quiet small filters__clear" onClick={clear}>
            {h.clear}
          </button>
        )}
      </div>
      {error && (
        <Notice tone="alert" role="alert">
          {errorText(error, t)}
        </Notice>
      )}
      {page === null ? (
        <div className="table-wrap history__list history__list--empty" aria-busy="true">
          <p className="aside">{t.loading}</p>
        </div>
      ) : page.rows.length === 0 ? (
        <div className="table-wrap history__list history__list--empty" aria-busy={busy}>
          <div className="history__empty">
            <h2>{any ? h.empty.title : h.none.title}</h2>
            <p>{any ? h.empty.text : h.none.text}</p>
            {any && (
              <button type="button" className="small" onClick={clear}>
                {h.clear}
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="table-wrap history__list" aria-busy={busy}>
          <table className="history__table">
            <colgroup>
              {['when', 'user', 'test', 'method', 'score', 'threshold', 'result', 'source', 'time', 'open'].map((name) => (
                <col key={name} className={`col-${name}`} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th scope="col">{h.headers.when}</th>
                <th scope="col">{h.headers.user}</th>
                <th scope="col">{h.headers.test}</th>
                <th scope="col">{h.headers.method}</th>
                <th scope="col" className="number">{h.headers.score}</th>
                <th scope="col" className="number">{h.headers.threshold}</th>
                <th scope="col">{h.headers.result}</th>
                <th scope="col">{h.headers.source}</th>
                <th scope="col" className="number">{h.headers.time}</th>
                <th scope="col"><span className="visually-hidden">{h.headers.parts}</span></th>
              </tr>
            </thead>
            {groups.map((group) => (
              <tbody key={group.key}>
                <tr className="day">
                  <th colSpan={10} scope="rowgroup">{group.label}</th>
                </tr>
                {group.rows.map((row) => (
                  <Row key={row.id} row={row} opened={open === row.id} onToggle={() => setOpen(open === row.id ? null : row.id)} />
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
      {page !== null && page.rows.length > 0 && (
        <div className="history__foot">
          <span>{page.total > page.rows.length ? h.shown(page.rows.length, page.total) : h.count(page.total)}</span>
          {page.next !== null && (
            <button type="button" className="small" onClick={showMore} disabled={more}>
              {h.more}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ row, opened, onToggle }: { row: HistoryRow; opened: boolean; onToggle(): void }) {
  const { t } = useSession()
  const h = t.history
  const combined = row.kind === 'combined'
  // A search that found another registered user above the threshold is the one an administrator must notice.
  const alert = row.mode === 'identify' && row.accepted && row.leader === 'other'
  return (
    <Fragment>
      <tr className={`attempt${combined ? ' attempt--combined' : ''}${opened ? ' attempt--open' : ''}`}>
        <td className="history__when">{time(row.at, t)}</td>
        <td className="history__user">
          {row.user === null ? (
            <span className="sub">{h.unknownUser}</span>
          ) : (
            <>
              <bdi>{row.user.username}</bdi>
              {row.user.disabled && <> <Tag>{h.disabled}</Tag></>}
            </>
          )}
        </td>
        <td>
          {h.types[combined ? 'combined' : row.modality]} <bdi className="mode">{row.mode === 'verify' ? '1:1' : '1:N'}</bdi>
          {row.mode === 'identify' && row.gallery_size !== null && (
            <span className="sub">{combined ? h.searched.people(row.gallery_size) : h.searched.templates(row.gallery_size)}</span>
          )}
        </td>
        <td>
          {combined ? (
            <>
              {h.modalities(row.parts.length)}
              <span className="sub">{h.policy(row.policy)}</span>
            </>
          ) : (
            <span className="latin">{methodName(row.algorithm)}</span>
          )}
        </td>
        <td className="number history__score">
          <b>{scoreOf(row, t)}</b>
        </td>
        <td className="number">
          {plain(row.threshold, t)}
          {!combined && row.provisional && <span className="sub">{h.provisional}</span>}
        </td>
        <td>
          <Tag tone={row.accepted ? (alert ? 'alert' : 'mark') : 'ink'}>{h.decision[row.mode][row.accepted ? 1 : 0]}</Tag>
          {row.mode === 'identify' && row.leader !== null && (
            <span className={`sub leader${alert ? ' leader--alert' : ''}`}>
              {alert && <Icon name="alert" />}
              {h.leader[row.leader]}
            </span>
          )}
        </td>
        <td>
          {originOf(row, t)}
          {!combined && row.capture_of !== null && <span className="sub">{h.captureOf(time(row.capture_of, t))}</span>}
        </td>
        <td className="number">{fixed(row.duration_ms / 1000, 2, t)}</td>
        <td className="history__open">
          {combined && (
            <button type="button" className="disclose" aria-expanded={opened} aria-controls={opened ? `parts-${row.id}` : undefined}
              aria-label={opened ? h.close : h.open} onClick={onToggle}>
              <Icon name="chevron" />
            </button>
          )}
        </td>
      </tr>
      {combined && opened && <Parts test={row} />}
    </Fragment>
  )
}

// A combined test's comparisons: the verdict first, the points stacked on one rail of 100, each comparison with its
// own threshold and decision, its evidence and its points, then the policy version that decided.
function Parts({ test }: { test: HistoryCombined }) {
  const { t } = useSession()
  const p = t.history.parts
  const ratio = 10 ** (((test.threshold - 50) * test.budget) / 50)
  const together = factor(10 ** test.evidence, t)
  const score = fixed(test.score, 1, t)
  const finger = test.parts.find((part) => part.modality === 'fingerprint')
  const others = test.parts.filter((part) => part.modality !== 'fingerprint')
  const carried = !test.accepted && finger !== undefined && !finger.accepted && others.length > 0 && others.every((part) => part.accepted)
  const weights = MODALITIES.map((modality) => String(test.weights[modality]))
  const pieces = test.parts.map((part, index) => ({
    part,
    from: test.parts.slice(0, index).reduce((sum, before) => sum + before.points, 0),
  }))
  return (
    <tr className="parts-row" id={`parts-${test.id}`}>
      <td colSpan={10}>
        <div className={`parts${test.accepted ? '' : ' not-accepted'}`}>
          <p className="parts__total">
            <b>{test.accepted ? p.accepted(together, score, plain(test.threshold, t)) : p.rejected(together, score, factor(ratio, t))}</b>
            {carried && <> {p.refused}</>}
          </p>
          <div className="stack-rail" style={{ '--at': (test.threshold / 100).toFixed(4) } as CSSProperties}>
            <div className="stack-rail__groove">
              {pieces.map(({ part, from }) => (
                <span key={part.modality} className="stack-rail__piece" data-modality={part.modality}
                  style={{ '--from': (from / 100).toFixed(4), '--size': (part.points / 100).toFixed(4) } as CSSProperties} />
              ))}
            </div>
            <div className="stack-rail__tick" />
            <div className="stack-rail__ends">
              <span>0</span>
              <span className="stack-rail__at">{p.accept(plain(test.threshold, t))}</span>
              <span>100</span>
            </div>
          </div>
          <table className="parts__table">
            <thead>
              <tr>
                {p.headers.map((name, index) => (
                  <th key={name} scope="col" className={index >= 2 && index !== 4 ? 'number' : undefined}>{name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {test.parts.map((part) => (
                <tr key={part.modality} data-modality={part.modality}>
                  <td>
                    <span className="parts__name"><i aria-hidden="true" />{t.history.types[part.modality]}</span>
                  </td>
                  <td><span className="latin">{methodName(part.algorithm)}</span></td>
                  <td className="number">{part.modality === 'fingerprint' ? fixed(part.score, 0, t) : fixed(part.score, 3, t)}</td>
                  <td className="number">{plain(part.threshold, t)}</td>
                  <td>{p.alone[part.accepted ? 1 : 0]}</td>
                  <td className="number">{(part.capped ? p.capped : p.factor)(factor(10 ** part.evidence, t))}</td>
                  <td className="number">
                    <b>{fixed(part.points, 1, t)}</b> <span className="parts__of">{p.of(part.weight)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="parts__policy">
            {p.policy(test.policy, `${weights.slice(0, -1).join(', ')}${p.and}${weights.at(-1)}`, plain(test.threshold, t), factor(ratio, t))}
          </p>
        </div>
      </td>
    </tr>
  )
}
