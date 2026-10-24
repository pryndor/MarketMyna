import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { createAlert, getLevels, getMarketStatus, getTradeChart, type ChartData, type MarketStatus, type PriceAlert } from '../../api/trade'
import type { SmartRow } from '../../api/scheduler'
import { cx } from '../../lib/cx'
import { errorMessage, num, price as fmtPrice } from '../../lib/format'
import { toast } from '../../lib/toast'
import { Button, Card, CardBody, CardHeader, Input, Segmented, Skeleton, Switch } from '../ui'
import { useLive } from './useLive'
import { CURRENCY, SERIES_COLORS, type PriceLevel } from './shared'

const TradeChart = lazy(() => import('./TradeChart'))

const INTERVALS = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '1d', label: '1D' },
  { value: '1wk', label: '1W' },
]
const INDICATORS = [
  { id: 'vwap', label: 'VWAP' },
  { id: 'ema9', label: 'EMA 9' },
  { id: 'ema21', label: 'EMA 21' },
  { id: 'ema50', label: 'EMA 50' },
  { id: 'ema200', label: 'EMA 200' },
  { id: 'supertrend', label: 'Supertrend' },
  { id: 'vwma', label: 'VWMA 13/19 + kNN (exp.)' },
  { id: 'knn_st', label: 'kNN Supertrend (exp.)' },
]
const OVERLAYS = [
  { id: 'pivots', label: 'Pivots' },
  { id: 'or', label: 'Opening range' },
  { id: 'alerts', label: 'My alerts' },
]
const PREFS_KEY = 'marketmyna.tradeChart'

interface Prefs {
  interval: string
  indicators: string[]
  overlays: string[]
  live: boolean
}

function loadPrefs(): Prefs {
  const fallback: Prefs = { interval: '5m', indicators: ['vwap', 'ema9', 'ema21'], overlays: ['pivots', 'alerts'], live: true }
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}') }
  } catch {
    return fallback
  }
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p))
  } catch {
    // not remembered in private mode
  }
}

export default function ChartTab({
  symbol,
  market,
  alerts,
  onAlertsChanged,
  onSize,
}: {
  symbol: string
  market: string
  alerts: PriceAlert[]
  onAlertsChanged: () => void
  onSize: (plan: { entry?: number; stop?: number; target?: number }) => void
}) {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs)
  const [data, setData] = useState<ChartData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [levels, setLevels] = useState<SmartRow | null>(null)
  const [picked, setPicked] = useState<number | null>(null)
  const [pickedText, setPickedText] = useState('')
  const [saving, setSaving] = useState(false)
  const intraday = !['1d', '1wk'].includes(prefs.interval)
  const cur = CURRENCY[market]

  function update(patch: Partial<Prefs>) {
    setPrefs((p) => {
      const next = { ...p, ...patch }
      savePrefs(next)
      return next
    })
  }

  const load = useCallback(
    (quiet = false) => {
      if (!quiet) {
        setData(null)
        setError(null)
      }
      return getTradeChart(symbol, market, prefs.interval, undefined, prefs.indicators)
        .then((d) => {
          setData(d)
          setError(null)
        })
        .catch((err) => !quiet && setError(errorMessage(err)))
    },
    [symbol, market, prefs.interval, prefs.indicators],
  )

  useEffect(() => {
    load()
  }, [load])

  // Live mode also reloads intraday bars every minute, which adds new candles
  // and recomputes the indicators.
  useEffect(() => {
    if (!prefs.live || !intraday) return
    const id = window.setInterval(() => load(true), 60_000)
    return () => window.clearInterval(id)
  }, [prefs.live, intraday, load])

  useEffect(() => {
    setLevels(null)
    setPicked(null)
    getLevels(symbol, market)
      .then(setLevels)
      .catch(() => setLevels(null))
  }, [symbol, market])

  const lines = useMemo(() => {
    const out: PriceLevel[] = []
    const on = (id: string) => prefs.overlays.includes(id)
    if (on('pivots') && data?.pivots) {
      for (const [k, v] of Object.entries(data.pivots))
        out.push({ price: v, label: k, color: k === 'P' ? '#9aa3b5' : k.startsWith('R') ? '#fb8a8a99' : '#34d39999', dashed: true })
    }
    if (on('or') && data?.opening_range) {
      out.push({ price: data.opening_range.high, label: 'OR high', color: '#f5b942', dashed: true })
      out.push({ price: data.opening_range.low, label: 'OR low', color: '#f5b942', dashed: true })
    }
    if (on('alerts')) {
      for (const a of alerts)
        if ((a.kind === 'price_above' || a.kind === 'price_below') && a.status === 'active')
          out.push({ price: a.value, label: `🔔 ${a.kind === 'price_above' ? '≥' : '≤'}`, color: '#6d8cff' })
    }
    if (picked != null) out.push({ price: picked, label: 'Picked', color: '#9aa3b5', dashed: true })
    return out
  }, [data, alerts, prefs.overlays, picked])

  const live = useLive(symbol, market, prefs.interval, prefs.live)
  const [status, setStatus] = useState<MarketStatus | null>(null)
  const [, setClock] = useState(0)

  useEffect(() => {
    const load = () => getMarketStatus(market).then(setStatus, () => setStatus(null))
    load()
    const id = window.setInterval(load, 60_000)
    return () => window.clearInterval(id)
  }, [market])

  // Re-render every few seconds so "last tick Ns ago" stays current.
  useEffect(() => {
    const id = window.setInterval(() => setClock((c) => c + 1), 3000)
    return () => window.clearInterval(id)
  }, [])
  const last = live?.price ?? data?.last?.close ?? null

  async function quickAlert(value: number, note = '') {
    if (last == null) return
    setSaving(true)
    try {
      await createAlert({ symbol, market, kind: value >= last ? 'price_above' : 'price_below', value, note })
      toast.success(`Alert set: ${symbol} ${value >= last ? '≥' : '≤'} ${fmtPrice(value, cur)}`)
      setPicked(null)
      onAlertsChanged()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const chip = (on: boolean, label: string, onClick: () => void, color?: string) => (
    <button
      key={label}
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        on ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
      )}
    >
      {color && <span className="h-2 w-2 rounded-full" style={{ background: color }} />}
      {label}
    </button>
  )

  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
      <Card>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Segmented options={INTERVALS} value={prefs.interval} onChange={(interval) => update({ interval })} size="sm" />
            <Switch checked={prefs.live} onChange={(on) => update({ live: on })} label={<span className="text-xs">Live</span>} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {INDICATORS.map((i) =>
              chip(
                prefs.indicators.includes(i.id),
                i.label,
                () => update({ indicators: toggle(prefs.indicators, i.id) }),
                i.id === 'supertrend' || i.id === 'knn_st'
                  ? 'linear-gradient(90deg,#34d399 50%,#fb8a8a 50%)'
                  : i.id === 'vwma'
                    ? 'linear-gradient(90deg,#38bdf8 50%,#fbbf24 50%)'
                    : SERIES_COLORS[i.id],
              ),
            )}
            <span className="mx-1 w-px bg-line" />
            {OVERLAYS.map((o) =>
              chip(prefs.overlays.includes(o.id), o.label, () => update({ overlays: toggle(prefs.overlays, o.id) })),
            )}
          </div>
          {(prefs.indicators.includes('vwma') || prefs.indicators.includes('knn_st')) && (
            <p className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
              Experimental nearest-neighbour (kNN) indicators.{' '}
              {data?.knn && `kNN now: lean ${data.knn.score >= 0 ? '+' : ''}${data.knn.score.toFixed(2)}, agreement ${Math.round(data.knn.agree * 100)}%, band ${data.knn.trend}. `}
              {prefs.indicators.includes('vwma') && 'VWMA arrows show each crossover with its kNN vote (faded = the filter would skip it). '}
              In our test on 19 large stocks (unseen last 3 of 10 years) both filters did worse than the plain signals, so
              treat them as something to study, not a signal; test any stock in the Backtest tab.
            </p>
          )}
          <LiveStatus status={status} live={prefs.live ? live : null} enabled={prefs.live} cur={cur} />
          <div className="h-[26rem] sm:h-[30rem]">
            {error ? (
              <div className="grid h-full place-items-center px-6 text-center text-xs text-muted">Chart unavailable: {error}</div>
            ) : data == null ? (
              <Skeleton className="h-full w-full" />
            ) : data.bars.length === 0 ? (
              <div className="grid h-full place-items-center text-xs text-muted">No {prefs.interval} bars for this range.</div>
            ) : (
              <Suspense fallback={<Skeleton className="h-full w-full" />}>
                <TradeChart
                  data={data}
                  live={live}
                  levels={lines}
                  intraday={intraday}
                  onPick={(p) => {
                    setPicked(p)
                    setPickedText(p.toFixed(p < 1 ? 4 : 2))
                  }}
                />
              </Suspense>
            )}
          </div>
          <p className="text-[12px] text-faint">
            Click the chart to pick a price for an alert. Crypto streams live from a major exchange; stock prices come from free
            sources and are about 15 minutes delayed. 1m covers 5 days, 5–30m one month, 1h six months.
          </p>
        </CardBody>
      </Card>

      <div className="space-y-6">
        <Card>
          <CardHeader title="Snapshot" description={data ? `${data.interval} · ${data.period}` : undefined} />
          <CardBody className="space-y-3 text-sm">
            <Row label="Last" value={fmtPrice(last, cur)} />
            <Row label={`RSI (${data?.interval ?? ''})`} value={num(data?.last?.rsi, 1)} />
            {/* Ranges only: no buy / sell points or stop (src/core/compliance.py). */}
            {levels && (
              <>
                <Row label="Normal range" value={`${fmtPrice(levels.normal_low, cur)} – ${fmtPrice(levels.normal_high, cur)}`} />
                <Row label="1-week range" value={`${fmtPrice(levels.week_low, cur)} – ${fmtPrice(levels.week_high, cur)}`} />
                <Row label="Daily trend" value={levels.trend ?? '—'} />
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button size="sm" variant="ghost" onClick={() => onSize({ entry: last ?? undefined })}>
                    Size a trade at this price
                  </Button>
                </div>
              </>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Quick alert" description="Click the chart or type a price." />
          <CardBody className="space-y-3">
            <div className="flex gap-2">
              <Input
                type="number"
                step="any"
                value={pickedText}
                onChange={(e) => {
                  setPickedText(e.target.value)
                  const v = parseFloat(e.target.value)
                  setPicked(Number.isFinite(v) ? v : null)
                }}
                placeholder={last != null ? String(last.toFixed(2)) : 'Price'}
              />
              <Button size="sm" loading={saving} disabled={picked == null || last == null} onClick={() => picked != null && quickAlert(picked)}>
                Set
              </Button>
            </div>
            {picked != null && last != null && (
              <p className="text-xs text-muted">
                Alerts when the price {picked >= last ? 'rises to' : 'falls to'} {fmtPrice(picked, cur)} (
                {(((picked - last) / last) * 100).toFixed(2)}% from {fmtPrice(last, cur)}).
              </p>
            )}
            {data?.pivots && (
              <div className="grid grid-cols-4 gap-1 text-[12px]">
                {Object.entries(data.pivots).map(([k, v]) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => {
                      setPicked(v)
                      setPickedText(v.toFixed(2))
                    }}
                    className="rounded border border-line px-1 py-0.5 text-start hover:border-line-strong"
                  >
                    <span className="text-muted">{k}</span> <span className="tabular">{num(v)}</span>
                  </button>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

/** Why the chart is (or isn't) moving: market open/closed, data delay,
 * last tick and its direction. */
function LiveStatus({
  status,
  live,
  enabled,
  cur,
}: {
  status: MarketStatus | null
  live: ReturnType<typeof useLive>
  enabled: boolean
  cur: string | undefined
}) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  useEffect(() => {
    if (!live || live.direction === 'flat') return
    setFlash(live.direction)
    const id = window.setTimeout(() => setFlash(null), 700)
    return () => window.clearTimeout(id)
  }, [live])

  if (!enabled) {
    return <div className="rounded-lg bg-raised px-3 py-2 text-xs text-muted">Live updates are off. Turn on Live to stream prices.</div>
  }
  const ago = live ? Math.max(0, Math.round((Date.now() - live.at) / 1000)) : null
  const closed = status && !status.open
  return (
    <div
      className={cx(
        'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg px-3 py-2 text-xs',
        closed ? 'bg-warn-soft text-fg' : 'bg-raised text-muted',
      )}
    >
      <span className="flex items-center gap-1.5 font-medium text-fg">
        <span className={cx('h-2 w-2 rounded-full', closed ? 'bg-warn' : 'animate-pulse bg-up')} />
        {!status
          ? 'Checking market…'
          : status.always_open
            ? `${status.name} trades 24/7`
            : status.open
              ? `${status.name} open · closes ${status.next_change_label}`
              : `${status.name} closed · opens ${status.next_change_label} (${status.session} local)`}
      </span>
      {live && (
        <span
          className={cx(
            'tabular rounded px-1.5 py-0.5 font-semibold transition-colors',
            flash === 'up' && 'bg-up-soft text-up',
            flash === 'down' && 'bg-down-soft text-down',
            !flash && 'text-fg',
          )}
        >
          {fmtPrice(live.price, cur)}
        </span>
      )}
      <span>
        {live
          ? `${live.source === 'binance' ? 'Exchange live' : 'Quote stream'} · last tick ${ago}s ago · ${live.count} ticks`
          : 'Connecting to the price stream…'}
      </span>
      {status && <span>Prices: {status.delay}</span>}
      {closed && <span className="basis-full text-muted">The chart shows the last session, so prices won't move until the market reopens. Try a crypto symbol (e.g. BTC-USD) to see live movement now.</span>}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted">{label}</span>
      <span className="tabular font-medium">{value}</span>
    </div>
  )
}
