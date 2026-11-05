import { useState } from 'react'
import { getIndexBoard, type IndexQuote } from '../api/macro'
import { cx } from '../lib/cx'
import { num, pct, signed, trendClass } from '../lib/format'
import { liveEvery, useFlash, useInsight } from '../lib/insight'
import { Icon } from './ui'

// Index values for the chosen Markets tab: a scrolling ticker of the main
// indices, and on "All indices" a board of tiles with the day's line, day
// range and readings (RSI, 50 / 200-day averages, 52-week range).
// Server side: marketmyna/services/index_board.py.

const OPEN_KEY = 'mm_index_board_open'

function readOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === '1'
  } catch {
    return false
  }
}

function writeOpen(on: boolean) {
  try {
    if (on) localStorage.setItem(OPEN_KEY, '1')
    else localStorage.removeItem(OPEN_KEY)
  } catch {
    // blocked storage: the board still opens for this visit
  }
}

const arrow = (v: number | null | undefined) => (v == null || v === 0 ? '◆' : v > 0 ? '▲' : '▼')

function changeText(i: IndexQuote): string {
  return i.change_unit === 'points' ? signed(i.change, 2) : pct(i.change_pct, 2)
}

function since(epoch: number | null): string {
  if (!epoch) return ''
  return new Date(epoch * 1000).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export default function IndexBoard({ market }: { market: string }) {
  const { data, error } = useInsight((signal) => getIndexBoard(market, signal), [market], liveEvery(60_000))
  const [open, setOpen] = useState(readOpen)
  const all = data?.groups.flatMap((g) => g.items) ?? []
  const flash = useFlash(Object.fromEntries(all.map((i) => [i.key, i.price])))

  function toggle() {
    writeOpen(!open)
    setOpen(!open)
  }

  const label = open ? 'Hide indices' : `All indices${all.length ? ` (${all.length})` : ''}`

  if (error && !data) return null
  // Every group scrolls by; the slide takes ~3.5 s per index so a long strip reads at the same pace.
  const groups = data?.groups ?? []
  const duration = `${Math.max(30, all.length * 3.5)}s`

  return (
    <section className="mb-4 rounded-lg border border-line bg-surface" aria-label="Index values">
      <div className="flex items-center gap-2">
        <div className="landing-strip flex min-w-0 flex-1 overflow-hidden py-2">
          {!data && <div className="h-5 w-full animate-pulse rounded bg-line/60 mx-3" />}
          {data && (
            <>
              <StripTrack groups={groups} flash={flash} duration={duration} />
              <StripTrack groups={groups} flash={flash} duration={duration} hidden />
            </>
          )}
        </div>
        {/* Phones: an icon only, so the ticker keeps the width; text from sm up. */}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-label={label}
          title={label}
          className="me-1.5 inline-flex shrink-0 items-center gap-1 rounded-md border border-line p-1.5 text-xs font-medium text-muted hover:text-fg sm:me-2 sm:px-2.5 sm:py-1"
        >
          <Icon name={open ? 'x' : 'grid'} className="h-4 w-4 sm:hidden" />
          <span className="hidden sm:inline">{label}</span>
        </button>
      </div>

      {open && data && (
        <div className="space-y-4 border-t border-line px-4 pb-4 pt-3">
          {data.groups.map((g) => (
            <div key={g.key}>
              <div className="mb-2 text-xs font-medium text-muted">{g.label}</div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {g.items.map((i) => (
                  <Tile key={i.key} item={i} flash={flash(i.key)} />
                ))}
              </div>
            </div>
          ))}
          <p className="text-[12px] text-faint">
            {data.source} RSI(14), 50 / 200-day averages and the 52-week range use daily closes; Up/Down counts the stocks in
            the index rising and falling today. Readings, not advice.
            {data.failed.length > 0 && ` Unavailable now: ${data.failed.join(', ')}.`}
          </p>
        </div>
      )}
    </section>
  )
}

function StripTrack({
  groups,
  flash,
  duration,
  hidden,
}: {
  groups: Array<{ key: string; label: string; items: IndexQuote[] }>
  flash: (k: string) => string
  duration: string
  hidden?: boolean
}) {
  return (
    <div className="landing-strip-track flex shrink-0 items-center gap-6 pe-6" style={{ animationDuration: duration }} aria-hidden={hidden || undefined}>
      {groups.map((g, n) => (
        <span key={g.key} className="flex items-center gap-6">
          {n > 0 && <span className="text-[11px] font-medium uppercase tracking-wide text-faint">{g.label}</span>}
          {g.items.map((i) => (
            <span key={i.key} className={cx('flex items-baseline gap-1.5 whitespace-nowrap rounded px-1 text-sm', flash(i.key))} title={i.note}>
              {i.open && <span className="h-1.5 w-1.5 self-center rounded-full bg-up" aria-label="trading now" />}
              <span className="text-muted">{i.label}</span>
              <span className="tabular font-semibold">{num(i.price, 2)}</span>
              <span className={cx('tabular text-xs', trendClass(i.change))}>
                {arrow(i.change)} {changeText(i)}
              </span>
            </span>
          ))}
        </span>
      ))}
    </div>
  )
}

function Tile({ item: i, flash }: { item: IndexQuote; flash: string }) {
  const range52 =
    i.high_52w != null && i.low_52w != null && i.high_52w > i.low_52w
      ? Math.round(((i.price - i.low_52w) / (i.high_52w - i.low_52w)) * 100)
      : null
  const readings: Array<{ label: string; value: string; tone: string; title: string }> = []
  if (i.rsi14 != null)
    readings.push({
      label: 'RSI',
      value: num(i.rsi14, 0),
      tone: 'text-fg',
      title: 'RSI(14) on daily closes: 70 and above is usually called overbought, 30 and below oversold',
    })
  if (i.vs_50d != null)
    readings.push({ label: '50D', value: pct(i.vs_50d, 1), tone: trendClass(i.vs_50d), title: 'Distance from the 50-day average' })
  if (i.vs_200d != null)
    readings.push({ label: '200D', value: pct(i.vs_200d, 1), tone: trendClass(i.vs_200d), title: 'Distance from the 200-day average' })
  if (i.advances != null && i.declines != null)
    readings.push({
      label: 'Up/Down',
      value: `${i.advances}/${i.declines}`,
      tone: i.advances > i.declines ? 'text-up' : i.advances < i.declines ? 'text-down' : 'text-fg',
      title: 'Stocks in the index up / down today',
    })
  if (i.pe != null) readings.push({ label: 'P/E', value: num(i.pe, 1), tone: 'text-fg', title: 'Index price to earnings' })
  if (range52 != null)
    readings.push({
      label: '52W',
      value: `${range52}%`,
      tone: 'text-fg',
      title: `Where it sits in its 52-week range: 0% = low ${num(i.low_52w, 2)}, 100% = high ${num(i.high_52w, 2)}`,
    })

  return (
    <div className={cx('rounded-lg bg-canvas px-3 py-2', flash)} title={i.note}>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="truncate font-medium text-muted">{i.label}</span>
        <span className={cx('shrink-0 text-[11px]', i.open ? 'text-up' : 'text-faint')}>
          {i.open ? 'Live' : i.updated ? `Closed · ${since(i.updated)}` : 'Closed'}
        </span>
      </div>
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="tabular text-lg font-semibold">{num(i.price, 2)}</div>
          <div className={cx('tabular whitespace-nowrap text-xs', trendClass(i.change))}>
            {arrow(i.change)} {signed(i.change, 2)} ({pct(i.change_pct, 2)})
          </div>
        </div>
        <Spark values={i.spark} base={i.prev_close} up={i.change >= 0} />
      </div>
      {i.day_low != null && i.day_high != null && i.day_high > i.day_low && (
        <DayRange low={i.day_low} high={i.day_high} value={i.price} />
      )}
      {readings.length > 0 ? (
        <div className="tabular mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
          {readings.map((r) => (
            <span key={r.label} title={r.title}>
              <span className="text-faint">{r.label}</span> <span className={r.tone}>{r.value}</span>
            </span>
          ))}
        </div>
      ) : (
        <div className="mt-1.5 text-[11px] text-faint">
          {i.expiry ? `Contract ${i.expiry} · vs previous settlement` : 'Daily readings not available'}
        </div>
      )}
    </div>
  )
}

/** The day's 5-minute line with the previous close as a dashed base. */
function Spark({ values, base, up }: { values: number[]; base: number; up: boolean }) {
  if (values.length < 2) return <div className="h-10 w-20 shrink-0" />
  const lo = Math.min(...values, base)
  const hi = Math.max(...values, base)
  const span = hi - lo || 1
  const w = 80
  const h = 40
  const y = (v: number) => h - 2 - ((v - lo) / span) * (h - 4)
  const pts = values.map((v, k) => `${((k / (values.length - 1)) * w).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const color = up ? 'var(--color-up)' : 'var(--color-down)'
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-10 w-20 shrink-0" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" x2={w} y1={y(base)} y2={y(base)} stroke="var(--color-line-strong)" strokeDasharray="2 2" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={color} fillOpacity="0.1" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function DayRange({ low, high, value }: { low: number; high: number; value: number }) {
  const pos = Math.max(0, Math.min(100, ((value - low) / (high - low)) * 100))
  return (
    <div className="mt-1.5" title={`Day low ${num(low, 2)} · high ${num(high, 2)}`}>
      <div className="relative h-1 rounded-full bg-line">
        <span className="absolute top-1/2 h-2.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-accent" style={{ left: `${pos}%` }} />
      </div>
      <div className="tabular mt-0.5 flex justify-between text-[11px] text-faint">
        <span>L {num(low, 2)}</span>
        <span>H {num(high, 2)}</span>
      </div>
    </div>
  )
}
