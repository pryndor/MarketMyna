import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCalendar, saveCalendarSettings, sendCalendarDigest, sentMessage, type CalendarEvent, type CalendarResponse, type CalendarSettings, type CustomOccurrence, type EconomicEvent, type EventType } from '../api/calendar'
import { analyzeLink } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { toast } from '../lib/toast'
import { EventAlerts, HOUR_OPTIONS, LEAD_OPTIONS, MyEventsPanel, StockPicker } from './EventSettings'
import { Button, Card, CardBody, CardHeader, Icon, Segmented, Select, Skeleton, Switch } from './ui'

const RANGES = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
]

const KIND_STYLE: Record<string, string> = {
  earnings: 'bg-accent-soft text-accent-fg',
  ex_dividend: 'bg-up-soft text-up',
  dividend: 'bg-raised text-muted',
  board_meeting: 'bg-warn-soft text-warn',
  corporate_action: 'bg-down-soft text-down',
}

const SHOW = [
  { value: 'all', label: 'All' },
  { value: 'stocks', label: 'My stocks' },
  { value: 'economy', label: 'Economy' },
  { value: 'markets', label: 'Markets' },
]

const ECON_STYLE: Record<string, string> = {
  central_bank: 'bg-warn-soft text-warn',
  inflation: 'bg-down-soft text-down',
  jobs: 'bg-accent-soft text-accent-fg',
  growth: 'bg-up-soft text-up',
  spending: 'bg-raised text-muted',
}

type DayGroup = { date: string; away: number; events: CalendarEvent[]; economic: EconomicEvent[]; custom: CustomOccurrence[] }

type Panel = 'list' | 'mine' | 'types' | null

const ECON_LABEL: Record<string, string> = {
  central_bank: 'Rates',
  inflation: 'Inflation',
  jobs: 'Jobs',
  growth: 'Growth',
  spending: 'Spending',
}

// Market events (holidays, sessions, expiries) are labelled by their type.
const MARKET_LABEL: Record<string, string> = {
  market_holiday: 'Closed',
  short_day: 'Short day',
  special_session: 'Special session',
  expiry: 'Expiry',
  index_rebalance: 'Index review',
  clock_change: 'Clock change',
}

const MARKET_STYLE: Record<string, string> = {
  market_holiday: 'bg-down-soft text-down',
  short_day: 'bg-warn-soft text-warn',
  special_session: 'bg-up-soft text-up',
  expiry: 'bg-accent-soft text-accent-fg',
  index_rebalance: 'bg-raised text-muted',
  clock_change: 'bg-raised text-muted',
}

const REGION_CHIP: Record<string, string> = { US: 'US', India: 'IN', 'Hong Kong': 'HK', China: 'CN', Global: 'GL' }
const REGION_MARKET: Record<string, string> = { US: 'us', India: 'india', 'Hong Kong': 'hong_kong', China: 'china_a' }

const isMarket = (e: EconomicEvent) => e.kind === 'market'
const econLabel = (e: EconomicEvent) => (isMarket(e) ? MARKET_LABEL[e.key ?? ''] ?? 'Market' : ECON_LABEL[e.kind] ?? 'Inflation')
const econStyle = (e: EconomicEvent) => (isMarket(e) ? MARKET_STYLE[e.key ?? ''] : ECON_STYLE[e.kind])

const econId = (e: EconomicEvent) => `${e.date}:${e.title}:${e.region}`

/** The headline number of a reading ("3.7% YoY in Aug, up from…" -> "3.7% YoY"). */
function shortReading(last: string): string {
  return last.split(/ in | \(|,|;/)[0].replace(/^Target range now |^Repo rate now /, '')
}

function EconDetail({ e }: { e: EconomicEvent }) {
  const exposure = e.exposure ?? []
  const idle = e.key === 'market_holiday'
  return (
    <div className="rounded-md border border-line bg-canvas/40 px-3 py-2 text-xs">
      <div className="font-medium text-fg">
        {e.title}
        <span className="font-normal text-faint"> · {e.note}</span>
      </div>
      {e.result && (
        <div className="mt-1">
          <span className="font-medium text-up">Out now: </span>
          <span className="tabular text-fg">{e.result}</span>
          {e.verdict && <span className="text-muted"> · {e.verdict}</span>}
        </div>
      )}
      {e.last && !e.result && (
        <div className="mt-1">
          <span className="text-muted">Last reading: </span>
          <span className="tabular text-fg">{e.last}</span>
        </div>
      )}
      {e.why && (
        <div className="mt-1">
          <span className="text-muted">Why it matters: </span>
          {e.why}
        </div>
      )}
      {exposure.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span className="text-muted">{idle ? `Your ${e.region} stocks that won't trade:` : `Your ${e.region} stocks:`}</span>
          {exposure.slice(0, 8).map((s) => (
            <Link key={s} to={analyzeLink({ symbol: s, market: REGION_MARKET[e.region] ?? 'us' })} className="font-mono text-accent hover:underline">
              {s}
            </Link>
          ))}
          {exposure.length > 8 && <span className="text-faint">+{exposure.length - 8} more</span>}
        </div>
      )}
      <div className="mt-1 text-faint">Source: {e.source}{e.estimated ? ' (usual schedule; may shift for holidays)' : ''}</div>
    </div>
  )
}

const GROUPS: { key: EventType['group']; label: string }[] = [
  { key: 'stocks', label: 'Your stocks' },
  { key: 'us', label: 'US economy' },
  { key: 'india', label: 'India economy' },
  { key: 'markets', label: 'Markets (all exchanges)' },
  { key: 'mine', label: 'Yours' },
]

/** Turn event types on / off; each comes with a plain-words explanation. */
function EventPicker({ types, hidden, onChange }: { types: EventType[]; hidden: string[]; onChange: (hidden: string[]) => void }) {
  const off = new Set(hidden)
  const toggle = (key: string) => onChange(off.has(key) ? hidden.filter((k) => k !== key) : [...hidden, key])
  return (
    <div className="rounded-lg border border-line bg-canvas/40 p-4">
      <p className="text-xs text-muted">Pick the events you want to see here and in your daily reminder.</p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {GROUPS.map((g) => (
          <fieldset key={g.key}>
            <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">{g.label}</legend>
            <div className="space-y-2">
              {types
                .filter((t) => t.group === g.key)
                .map((t) => (
                  <label key={t.key} className="flex cursor-pointer items-start gap-2">
                    <input type="checkbox" className="mt-0.5 accent-accent" checked={!off.has(t.key)} onChange={() => toggle(t.key)} />
                    <span>
                      <span className="block text-sm font-medium">{t.name}</span>
                      <span className="block text-xs text-muted">{t.about}</span>
                    </span>
                  </label>
                ))}
            </div>
          </fieldset>
        ))}
      </div>
    </div>
  )
}

function dayLabel(iso: string, away: number): string {
  if (away === 0) return 'Today'
  if (away === 1) return 'Tomorrow'
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

/** Upcoming earnings / dividend dates for everything in watchlists and portfolios. */
export type EventSummary = { total: number; today: number }

/** onSummary reports how many events are in view (the Watchlist page shows it on its tab). */
export default function EventCalendar({ onSummary, className = 'mt-6' }: { onSummary?: (s: EventSummary) => void; className?: string } = {}) {
  const [days, setDays] = useState('30')
  const [data, setData] = useState<CalendarResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [settings, setSettings] = useState<CalendarSettings | null>(null)
  const [sending, setSending] = useState(false)
  const [show, setShow] = useState('all')
  const [panel, setPanel] = useState<Panel>(null)
  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? null : p))
  const [reload, setReload] = useState(0)
  const [toggled, setToggled] = useState<Set<string>>(new Set())

  // Today / tomorrow open by default; a click flips any event.
  const isOpen = (e: EconomicEvent) => (e.days_away <= 1) !== toggled.has(econId(e))
  const flip = (e: EconomicEvent) =>
    setToggled((prev) => {
      const next = new Set(prev)
      if (!next.delete(econId(e))) next.add(econId(e))
      return next
    })

  const shownDays = useRef(days)

  useEffect(() => {
    let live = true
    // A new range shows the skeleton; a refresh after a save swaps the data in place.
    if (shownDays.current !== days) {
      shownDays.current = days
      setData(null)
    }
    setError(null)
    getCalendar(Number(days))
      .then((res) => {
        if (!live) return
        setData(res)
        setSettings(res.settings)
      })
      .catch((err) => live && setError(errorMessage(err)))
    return () => {
      live = false
    }
  }, [days, reload])

  useEffect(() => {
    if (!data || !onSummary) return
    const all = [...(data.events ?? []), ...(data.economic ?? [])]
    onSummary({ total: all.length, today: all.filter((e) => e.days_away === 0).length })
  }, [data, onSummary])

  const byDay = useMemo(() => {
    const map = new Map<string, DayGroup>()
    const group = (date: string, away: number) => {
      if (!map.has(date)) map.set(date, { date, away, events: [], economic: [], custom: [] })
      return map.get(date)!
    }
    const mine = show === 'all' || show === 'stocks'
    if (mine) for (const e of data?.events ?? []) group(e.date, e.days_away).events.push(e)
    if (mine) for (const e of data?.custom ?? []) group(e.date, e.days_away).custom.push(e)
    for (const e of data?.economic ?? []) {
      if (show === 'all' || (show === 'economy' && !isMarket(e)) || (show === 'markets' && isMarket(e))) group(e.date, e.days_away).economic.push(e)
    }
    return [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
  }, [data, show])

  async function patch(change: Partial<CalendarSettings>) {
    if (!settings) return
    const previous = settings
    setSettings({ ...settings, ...change })
    try {
      setSettings(await saveCalendarSettings(change))
    } catch (err) {
      setSettings(previous)
      toast.error(errorMessage(err))
    }
  }

  async function setHidden(hidden_events: string[]) {
    await patch({ hidden_events })
    setReload((n) => n + 1)
  }

  async function setMyList(next: { sources: string[] | null; symbols: CalendarSettings['extra_symbols'] }) {
    if (!settings) return
    setSettings({ ...settings, sources: next.sources, extra_symbols: next.symbols })
    try {
      setSettings(
        await saveCalendarSettings({
          ...(next.sources === null ? { all_lists: true } : { sources: next.sources }),
          extra_symbols: next.symbols,
        }),
      )
      setReload((n) => n + 1)
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const refresh = () => setReload((n) => n + 1)

  async function sendNow() {
    setSending(true)
    try {
      const m = sentMessage(await sendCalendarDigest())
      toast[m.tone](m.text)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <Card className={className}>
      <CardHeader
        title="Upcoming events"
        icon="clock"
        description={
          data
            ? `Results, dividends and corporate actions for the ${data.symbols} stock${data.symbols === 1 ? '' : 's'} in your events list, market holidays and special sessions in India, US, Hong Kong and China, rate decisions, key US / India data and your own dates`
            : 'Earnings, dividends, market holidays and economic releases'
        }
      />
      <CardBody className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented size="sm" value={show} onChange={setShow} options={SHOW} />
          <Segmented size="sm" value={days} onChange={setDays} options={RANGES} />
          {settings && data?.event_types && (
            <div className="flex flex-wrap gap-1 sm:ms-auto">
              <Button variant={panel === 'list' ? 'secondary' : 'ghost'} size="sm" icon="star" aria-expanded={panel === 'list'} onClick={() => togglePanel('list')}>
                My stocks list
              </Button>
              <Button variant={panel === 'mine' ? 'secondary' : 'ghost'} size="sm" icon="plus" aria-expanded={panel === 'mine'} onClick={() => togglePanel('mine')}>
                Add my event
              </Button>
              <Button variant={panel === 'types' ? 'secondary' : 'ghost'} size="sm" icon="settings" aria-expanded={panel === 'types'} onClick={() => togglePanel('types')}>
                Choose events{settings.hidden_events?.length ? ` (${data.event_types.length - settings.hidden_events.length}/${data.event_types.length})` : ''}
              </Button>
            </div>
          )}
        </div>
        {panel === 'types' && settings && data?.event_types && (
          <EventPicker types={data.event_types} hidden={settings.hidden_events ?? []} onChange={setHidden} />
        )}
        {panel === 'list' && settings && (
          <div className="rounded-lg border border-line bg-canvas/40 p-4">
            <p className="mb-3 text-xs text-muted">
              The stocks whose earnings and dividends show here and in your daily reminder. Pick the lists that count and add any other stock.
            </p>
            <StockPicker lists={data?.lists ?? []} sources={settings.sources} symbols={settings.extra_symbols ?? []} onChange={setMyList} />
          </div>
        )}
        {panel === 'mine' && (
          <div className="rounded-lg border border-line bg-canvas/40 p-4">
            <p className="mb-3 text-xs text-muted">Your own dates: they show in this list and in your reminders, once or every month / year.</p>
            <MyEventsPanel events={data?.custom_all ?? []} onChanged={refresh} />
          </div>
        )}
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <Skeleton className="h-32 w-full" />}
        {data && byDay.length === 0 && (
          <p className="py-4 text-center text-sm text-muted">
            {show === 'stocks' && data.symbols === 0 ? 'Add stocks to a watchlist or portfolio to see their events here.' : `No published events in the next ${days} days.`}
          </p>
        )}
        {byDay.length > 0 && (
          <ol className="space-y-3">
            {byDay.map((g) => (
              <li key={g.date} className="grid gap-2 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
                <div className={cx('text-sm font-medium', g.away <= 1 ? 'text-warn' : 'text-muted')}>{dayLabel(g.date, g.away)}</div>
                <ul className="flex flex-wrap gap-2">
                  {g.custom.map((e) => (
                    <li key={`custom:${e.id}`}>
                      <span
                        className="inline-flex max-w-full items-center gap-2 rounded-md border border-accent/40 bg-accent-soft/40 px-2 py-1 text-sm"
                        title={e.note || undefined}
                      >
                        <Icon name="star" className="h-3.5 w-3.5 text-accent" />
                        <span>{e.title}</span>
                        <span className="rounded bg-raised px-1.5 py-0.5 text-[11px] text-muted">{e.repeat === 'none' ? 'Mine' : e.repeat === 'monthly' ? 'Monthly' : 'Yearly'}</span>
                        {e.note && <span className="hidden min-w-0 max-w-56 truncate text-xs text-faint sm:inline">{e.note}</span>}
                      </span>
                    </li>
                  ))}
                  {g.events.map((e) => (
                    <li key={`${e.symbol}:${e.kind}`}>
                      <Link
                        to={analyzeLink({ symbol: e.symbol, market: e.market })}
                        className="inline-flex items-center gap-2 rounded-md border border-line px-2 py-1 text-sm hover:border-line-strong"
                        title={[...e.followed_in, e.detail, e.confirmed ? 'Date confirmed by the exchange' : ''].filter(Boolean).join(' · ')}
                      >
                        <span className="font-mono">{e.symbol}</span>
                        <span className={cx('rounded px-1.5 py-0.5 text-[11px]', KIND_STYLE[e.kind])}>{e.label}</span>
                        {e.confirmed && e.kind === 'earnings' && <Icon name="check" className="h-3.5 w-3.5 text-up" />}
                        {e.detail && e.kind !== 'earnings' && <span className="hidden min-w-0 max-w-64 truncate text-xs text-muted sm:inline">{e.detail}</span>}
                        {e.eps_estimate != null && <span className="tabular text-xs text-faint">EPS est. {num(e.eps_estimate)}</span>}
                      </Link>
                    </li>
                  ))}
                  {g.economic.map((e) => (
                    <li key={`${e.title}:${e.region}`}>
                      <button
                        type="button"
                        onClick={() => flip(e)}
                        aria-expanded={isOpen(e)}
                        className={cx(
                          'inline-flex items-center gap-2 rounded-md border border-dashed px-2 py-1 text-start text-sm hover:border-line-strong',
                          isOpen(e) ? 'border-line-strong bg-raised/50' : 'border-line',
                          e.importance === 'medium' && !isOpen(e) && 'opacity-75',
                        )}
                      >
                        <span className="rounded bg-raised px-1 text-[10px] font-semibold text-muted">{REGION_CHIP[e.region] ?? e.region}</span>
                        <span>{e.title}</span>
                        <span className={cx('rounded px-1.5 py-0.5 text-[11px]', econStyle(e))}>{econLabel(e)}</span>
                        {e.result ? (
                          <span className="tabular text-xs font-medium text-up">Out: {shortReading(e.result)}</span>
                        ) : (
                          e.last && <span className="tabular text-xs text-muted">Last {shortReading(e.last)}</span>
                        )}
                        {e.local_time && <span className="tabular text-xs text-faint">{e.local_time}{e.estimated ? '*' : ''}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
                {g.economic.some(isOpen) && (
                  <div className="space-y-2 sm:col-start-2">
                    {g.economic.filter(isOpen).map((e) => (
                      <EconDetail key={econId(e)} e={e} />
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}

        {(data?.economic?.length ?? 0) > 0 && show !== 'stocks' && (
          <p className="text-[12px] text-faint">
            Click an economic or market event for what it means for your stocks (and, for data releases, the last reading). Times are in {settings?.timezone ?? 'your timezone'}. * Usual schedule, can
            shift for holidays. Indian results dates with a ✓ are confirmed by the exchange. Sources: central banks, official statistics agencies and the exchanges' own holiday lists.
            {data?.economic_warnings?.length ? ` ${data.economic_warnings.join('; ')}.` : ''}
          </p>
        )}

        {settings && (
          <div className="space-y-3 border-t border-line pt-4">
            <Switch
              checked={settings.notify}
              onChange={(notify) => patch({ notify })}
              label="Daily reminder"
              description="One message on your alert channels (Telegram, push…) with everything above: your stocks list, the event types you chose and your own dates, plus the last reading of each economic release. When a US data release is out you also get its new number."
            />
            {settings.notify && (
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <Select
                  className="w-auto"
                  value={String(settings.days_before)}
                  onChange={(e) => patch({ days_before: Number(e.target.value) })}
                  options={LEAD_OPTIONS}
                />
                <span className="text-muted">at</span>
                <Select className="w-auto" value={String(settings.notify_hour)} onChange={(e) => patch({ notify_hour: Number(e.target.value) })} options={HOUR_OPTIONS} />
                <span className="text-xs text-faint">{settings.timezone}</span>
                <Button variant="ghost" size="sm" icon="send" loading={sending} onClick={sendNow}>
                  Send now
                </Button>
              </div>
            )}
          </div>
        )}
        {settings && data?.event_types && (
          <div className="border-t border-line pt-4">
            <EventAlerts alerts={data.alerts ?? []} lists={data.lists ?? []} types={data.event_types} onChanged={refresh} />
          </div>
        )}
      </CardBody>
    </Card>
  )
}
