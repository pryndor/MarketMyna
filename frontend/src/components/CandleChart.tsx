import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { compact, num, pct } from '../lib/format'
import { useTheme } from '../lib/theme'

export interface Candle {
  time: number // unix seconds
  open: number
  high: number
  low: number
  close: number
  volume: number | null
}

const MA_COLORS: Record<number, string> = { 20: '#f5b942', 50: '#6d8cff', 200: '#c77dff' }

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function movingAverage(candles: Candle[], period: number) {
  const out: Array<{ time: Time; value: number }> = []
  let sum = 0
  candles.forEach((c, i) => {
    sum += c.close
    if (i >= period) sum -= candles[i - period].close
    if (i >= period - 1) out.push({ time: c.time as UTCTimestamp, value: sum / period })
  })
  return out
}

/** TradingView-style candlesticks with volume, optional moving averages,
 * zoom/pan and an OHLC readout that follows the crosshair. */
export default function CandleChart({
  candles,
  averages,
  intraday,
}: {
  candles: Candle[]
  averages: number[]
  intraday: boolean
}) {
  const container = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [hover, setHover] = useState<Candle | null>(null)
  const theme = useTheme() // colors are read once per chart, so rebuild on theme change

  useEffect(() => {
    const el = container.current
    if (!el || candles.length === 0) return

    const up = cssVar('--color-up', '#34d399')
    const down = cssVar('--color-down', '#fb8a8a')
    const faint = cssVar('--color-faint', '#8c95aa')
    const line = cssVar('--color-line', '#2a3142')

    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: faint, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: line } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    })
    chartRef.current = chart

    const series = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
    })
    series.setData(candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })))

    if (candles.some((c) => c.volume)) {
      const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' })
      // Volume sits in the bottom fifth, under the candles.
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
      series.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } })
      volume.setData(
        candles.map((c) => ({
          time: c.time as UTCTimestamp,
          value: c.volume ?? 0,
          color: `${c.close >= c.open ? up : down}55`,
        })),
      )
    }

    for (const period of averages) {
      if (candles.length <= period) continue
      const ma = chart.addSeries(LineSeries, {
        color: MA_COLORS[period] ?? faint,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ma.setData(movingAverage(candles, period))
    }

    chart.timeScale().fitContent()

    const byTime = new Map(candles.map((c) => [c.time, c]))
    chart.subscribeCrosshairMove((param) => {
      setHover(param.time != null ? (byTime.get(param.time as number) ?? null) : null)
    })

    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [candles, averages, intraday, theme])

  const shown = hover ?? candles[candles.length - 1]
  const change = shown ? ((shown.close - shown.open) / shown.open) * 100 : null
  const when = shown
    ? new Date(shown.time * 1000).toLocaleString(undefined, intraday ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' })
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
          {shown.volume != null && <span>Vol {compact(shown.volume)}</span>}
        </div>
      )}
      <div ref={container} className="h-full w-full" />
    </div>
  )
}
