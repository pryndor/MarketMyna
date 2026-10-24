import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { Bar, ChartData } from '../../api/trade'
import { compact, num, pct } from '../../lib/format'
import { useTheme } from '../../lib/theme'
import { SERIES_COLORS, type PriceLevel } from './shared'

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

/** Candles + volume + indicator overlays + horizontal levels (pivots,
 * alerts, buy/sell points). Click anywhere to pick that price. */
export default function TradeChart({
  data,
  levels,
  intraday,
  onPick,
  live,
}: {
  data: ChartData
  levels: PriceLevel[]
  intraday: boolean
  onPick?: (price: number) => void
  /** forming candle (crypto) or latest price (stocks) to paint without a rebuild */
  live?: { bar: Bar | null; price: number } | null
}) {
  const container = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<Bar | null>(null)
  const theme = useTheme()
  const pickRef = useRef(onPick)
  pickRef.current = onPick
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const lastBarRef = useRef<Bar | null>(null)
  // Zoom / scroll survive the periodic data refresh of the same chart.
  const viewRef = useRef<{ key: string; range: { from: number; to: number } | null } | null>(null)

  useEffect(() => {
    const el = container.current
    if (!el || data.bars.length === 0) return
    const up = cssVar('--color-up', '#34d399')
    const down = cssVar('--color-down', '#fb8a8a')
    const faint = cssVar('--color-faint', '#8c95aa')
    const line = cssVar('--color-line', '#2a3142')

    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: faint, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: line } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: CrosshairMode.Normal },
    })

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
    })
    candles.setData(data.bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })))
    candlesRef.current = candles
    lastBarRef.current = data.bars[data.bars.length - 1]

    if (data.bars.some((b) => b.volume)) {
      const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' })
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
      candles.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.22 } })
      volume.setData(
        data.bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: `${b.close >= b.open ? up : down}55` })),
      )
    }

    for (const [name, points] of Object.entries(data.series)) {
      if (!points.length) continue
      // Trend lines come as up / down legs (Supertrend and the kNN adaptive Supertrend).
      const leg = name.endsWith('_up') ? 'up' : name.endsWith('_down') ? 'down' : null
      const color = leg === 'up' ? up : leg === 'down' ? down : (SERIES_COLORS[name] ?? faint)
      const s = chart.addSeries(LineSeries, {
        color,
        lineWidth: leg ? 2 : 1,
        lineStyle: name.startsWith('knn_st') ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      // Supertrend is split into up / down legs; gaps between legs are
      // whitespace points so the line breaks where the trend flips.
      if (leg) {
        const byTime = new Map(points.map((p) => [p.time, p.value]))
        s.setData(
          data.bars.map((b) =>
            byTime.has(b.time) ? { time: b.time as UTCTimestamp, value: byTime.get(b.time)! } : { time: b.time as UTCTimestamp },
          ),
        )
      } else {
        s.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })))
      }
    }

    if (data.markers?.length) {
      createSeriesMarkers(
        candles,
        data.markers.map((m) => {
          const buy = m.kind.startsWith('buy')
          const skip = m.kind.endsWith('_skip')
          return {
            time: m.time as UTCTimestamp,
            position: buy ? ('belowBar' as const) : ('aboveBar' as const),
            shape: buy ? ('arrowUp' as const) : ('arrowDown' as const),
            color: `${buy ? up : down}${skip ? '66' : ''}`,
            text: m.text,
          }
        }),
      )
    }

    for (const lvl of levels) {
      candles.createPriceLine({
        price: lvl.price,
        color: lvl.color,
        lineWidth: 1,
        lineStyle: lvl.dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title: lvl.label,
      })
    }

    const viewKey = `${data.symbol}|${data.market}|${data.interval}`
    const saved = viewRef.current
    if (saved && saved.key === viewKey && saved.range) {
      chart.timeScale().setVisibleLogicalRange(saved.range)
    } else {
      chart.timeScale().fitContent()
      if (intraday && data.bars.length > 150) {
        // Open on the latest ~150 bars; scroll or zoom out for the rest.
        chart.timeScale().setVisibleLogicalRange({ from: data.bars.length - 150, to: data.bars.length + 4 })
      }
    }

    const byTime = new Map(data.bars.map((b) => [b.time, b]))
    chart.subscribeCrosshairMove((param) => setHover(param.time != null ? (byTime.get(param.time as number) ?? null) : null))
    chart.subscribeClick((param) => {
      if (!param.point || !pickRef.current) return
      const price = candles.coordinateToPrice(param.point.y)
      if (price != null && Number.isFinite(price)) pickRef.current(Number(price))
    })

    return () => {
      const range = chart.timeScale().getVisibleLogicalRange()
      viewRef.current = { key: viewKey, range: range ? { from: range.from, to: range.to } : null }
      candlesRef.current = null
      chart.remove()
    }
  }, [data, levels, intraday, theme])

  // Live ticks update only the last candle (or start the next one).
  useEffect(() => {
    const series = candlesRef.current
    const last = lastBarRef.current
    if (!series || !last || !live) return
    let bar: Bar
    if (live.bar) {
      if (live.bar.time < last.time) return
      bar = live.bar.time === last.time ? { ...live.bar } : live.bar
    } else {
      bar = { ...last, close: live.price, high: Math.max(last.high, live.price), low: Math.min(last.low, live.price) }
    }
    try {
      series.update({ time: bar.time as UTCTimestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close })
      lastBarRef.current = bar
    } catch {
      // out-of-order tick after a reload - the next full refresh fixes it
    }
  }, [live])

  const shown = hover ?? data.bars[data.bars.length - 1]
  const change = shown ? ((shown.close - shown.open) / shown.open) * 100 : null
  // Bar times are exchange wall-clock seconds, so format them as UTC.
  const when = shown
    ? new Date(shown.time * 1000).toLocaleString(undefined, {
        timeZone: 'UTC',
        ...(intraday ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' }),
      })
    : ''

  return (
    <div className="relative h-full w-full">
      {shown && (
        <div className="tabular pointer-events-none absolute top-1 start-1 z-10 flex flex-wrap gap-x-3 rounded-md bg-surface/80 px-2 py-1 text-[12px] text-muted backdrop-blur-sm">
          <span>{when}</span>
          <span>O <b className="text-fg">{num(shown.open)}</b></span>
          <span>H <b className="text-fg">{num(shown.high)}</b></span>
          <span>L <b className="text-fg">{num(shown.low)}</b></span>
          <span>C <b className="text-fg">{num(shown.close)}</b></span>
          <span className={change != null && change >= 0 ? 'text-up' : 'text-down'}>{pct(change)}</span>
          {shown.volume > 0 && <span>Vol {compact(shown.volume)}</span>}
        </div>
      )}
      <div ref={container} className="h-full w-full" />
    </div>
  )
}
