import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getHistory, type HistoryRow } from '../api/stocks'
import { cx } from '../lib/cx'
import { errorMessage, num, pct } from '../lib/format'
import { PERIODS } from '../lib/options'
import type { Candle } from './CandleChart'
import { Segmented, Skeleton } from './ui'

// The candlestick library only loads once someone switches to candles.
const CandleChart = lazy(() => import('./CandleChart'))

type Mode = 'line' | 'candles'
type Interval = 'auto' | '1d' | '1wk'

const MODES = [
  { value: 'line', label: 'Line' },
  { value: 'candles', label: 'Candles' },
]
const INTERVALS = [
  { value: 'auto', label: 'Auto' },
  { value: '1d', label: 'Daily' },
  { value: '1wk', label: 'Weekly' },
]
const MA_PERIODS = [20, 50, 200]
const PREFS_KEY = 'marketmyna.chart'

interface Prefs {
  mode: Mode
  interval: Interval
  averages: number[]
}

function loadPrefs(): Prefs {
  const fallback: Prefs = { mode: 'line', interval: 'auto', averages: [20, 50] }
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}') }
  } catch {
    return fallback
  }
}

function savePrefs(prefs: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
  } catch {
    // storage unavailable (private mode) - the choice just isn't remembered
  }
}

/** History rows differ slightly by source ("Date" / "date" / "Datetime"),
 * so the date and OHLC columns are looked up by name. */
function toCandles(rows: HistoryRow[]): Candle[] {
  if (!rows.length) return []
  const keys = Object.keys(rows[0])
  const dateKey = keys.find((k) => /date|time|index/i.test(k))
  const col = (name: string) => keys.find((k) => k.toLowerCase() === name)
  const [o, h, l, c, v] = ['open', 'high', 'low', 'close', 'volume'].map(col)
  if (!dateKey || !c) return []
  const seen = new Set<number>()
  return rows
    .map((r) => {
      const close = Number(r[c])
      return {
        time: Math.floor(new Date(r[dateKey] as string | number).getTime() / 1000),
        open: o ? Number(r[o]) : close,
        high: h ? Number(r[h]) : close,
        low: l ? Number(r[l]) : close,
        close,
        volume: v ? Number(r[v]) : null,
      }
    })
    .filter((x) => Number.isFinite(x.time) && Number.isFinite(x.close) && !seen.has(x.time) && seen.add(x.time))
    .sort((a, b) => a.time - b.time)
}

export default function PriceChart({ symbol, market }: { symbol: string; market: string }) {
  const [period, setPeriod] = useState('6mo')
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs)
  const [rows, setRows] = useState<HistoryRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const interval = prefs.interval === 'auto' ? (period === '5y' ? '1wk' : '1d') : prefs.interval

  useEffect(() => {
    let cancelled = false
    setRows(null)
    setError(null)
    getHistory(symbol, market, period, interval)
      .then((r) => !cancelled && setRows(r))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market, period, interval])

  function update(patch: Partial<Prefs>) {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      savePrefs(next)
      return next
    })
  }

  const candles = useMemo(() => (rows ? toCandles(rows) : []), [rows])
  const points = useMemo(() => candles.map((c) => ({ t: c.time * 1000, close: c.close })), [candles])

  const change = useMemo(() => {
    if (points.length < 2) return null
    const first = points[0].close
    return ((points[points.length - 1].close - first) / first) * 100
  }, [points])

  const up = (change ?? 0) >= 0
  const stroke = up ? 'var(--color-up)' : 'var(--color-down)'
  const longRange = period === '1y' || period === '5y'
  const candleMode = prefs.mode === 'candles'

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented options={MODES} value={prefs.mode} onChange={(m) => update({ mode: m as Mode })} size="sm" />
          <div className="text-xs text-muted">
            Period change{' '}
            <span className={`tabular font-semibold ${change == null ? '' : up ? 'text-up' : 'text-down'}`}>{pct(change)}</span>
          </div>
        </div>
        <Segmented options={PERIODS} value={period} onChange={setPeriod} size="sm" />
      </div>

      {candleMode && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Segmented options={INTERVALS} value={prefs.interval} onChange={(i) => update({ interval: i as Interval })} size="sm" />
          <div className="flex items-center gap-1.5 text-xs text-muted">
            <span>Moving averages</span>
            {MA_PERIODS.map((p) => {
              const on = prefs.averages.includes(p)
              return (
                <button
                  key={p}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    update({ averages: on ? prefs.averages.filter((x) => x !== p) : [...prefs.averages, p].sort((a, b) => a - b) })
                  }
                  className={cx(
                    'rounded-full border px-2 py-0.5 font-medium',
                    on ? 'border-accent bg-accent-soft text-fg' : 'border-line hover:text-fg',
                  )}
                >
                  {p}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className={candleMode ? 'h-80' : 'h-56'}>
        {error ? (
          <div className="grid h-full place-items-center text-xs text-muted">History unavailable: {error}</div>
        ) : rows == null ? (
          <Skeleton className="h-full w-full" />
        ) : points.length === 0 ? (
          <div className="grid h-full place-items-center text-xs text-muted">No price history for this range.</div>
        ) : candleMode ? (
          <Suspense fallback={<Skeleton className="h-full w-full" />}>
            <CandleChart candles={candles} averages={prefs.averages} intraday={false} />
          </Suspense>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--color-line)" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                domain={['dataMin', 'dataMax']}
                scale="time"
                tickFormatter={(t: number) =>
                  new Date(t).toLocaleDateString(undefined, longRange ? { month: 'short', year: '2-digit' } : { month: 'short', day: 'numeric' })
                }
                tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                minTickGap={40}
              />
              <YAxis
                domain={['auto', 'auto']}
                orientation="right"
                width={56}
                tickFormatter={(v: number) => num(v, v >= 1000 ? 0 : 2)}
                tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ stroke: 'var(--color-line-strong)' }}
                contentStyle={{
                  background: 'var(--color-raised)',
                  border: '1px solid var(--color-line-strong)',
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(t) => new Date(Number(t)).toLocaleDateString()}
                formatter={(v) => [num(Number(v)), 'Close']}
              />
              <Area type="monotone" dataKey="close" stroke={stroke} strokeWidth={1.75} fill="url(#priceFill)" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
      {candleMode && (
        <p className="mt-1.5 text-[12px] text-faint">
          Scroll to zoom, drag to pan, hover a candle for open / high / low / close. A moving average appears once the
          period has more bars than its length (e.g. pick 1Y for the 200-day line).
        </p>
      )}
    </div>
  )
}
