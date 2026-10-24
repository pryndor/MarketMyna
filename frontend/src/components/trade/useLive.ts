import { useEffect, useState } from 'react'
import type { Bar } from '../../api/trade'

interface LiveTick {
  price: number
  changePercent: number | null
  /** crypto: the forming candle itself (Binance); stocks: null */
  bar: Bar | null
  source: 'binance' | 'server'
  at: number
  /** ticks received since the stream opened (proves it's alive even when the price is flat) */
  count: number
  /** price moved versus the previous tick */
  direction: 'up' | 'down' | 'flat'
}

const BINANCE_INTERVAL: Record<string, string> = { '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '1d': '1d', '1wk': '1w' }

function binancePair(symbol: string): string {
  const base = symbol.toUpperCase().split('-')[0]
  return (base.endsWith('USDT') ? base : `${base}USDT`).toLowerCase()
}

/** Live price for the chart. Crypto: Binance's kline WebSocket (true real
 * time, straight from the browser). Stocks: the server's SSE quote stream
 * (as fresh as the data source; ~15 min delayed on free data). */
export function useLive(symbol: string, market: string, interval: string, enabled: boolean): LiveTick | null {
  const [tick, setTick] = useState<LiveTick | null>(null)

  // Adds the running count and the move versus the previous tick.
  const push = (next: Omit<LiveTick, 'count' | 'direction'>) =>
    setTick((prev) => ({
      ...next,
      count: (prev?.count ?? 0) + 1,
      direction: !prev || next.price === prev.price ? 'flat' : next.price > prev.price ? 'up' : 'down',
    }))

  useEffect(() => {
    setTick(null)
    if (!enabled || !symbol) return
    if (market === 'crypto') {
      const url = `wss://stream.binance.com:9443/ws/${binancePair(symbol)}@kline_${BINANCE_INTERVAL[interval] ?? '1m'}`
      let ws: WebSocket | null = null
      let retry: number | undefined
      let closed = false
      const connect = () => {
        ws = new WebSocket(url)
        ws.onmessage = (ev) => {
          const k = JSON.parse(ev.data)?.k
          if (!k) return
          const bar: Bar = {
            time: Math.floor(k.t / 1000),
            open: +k.o,
            high: +k.h,
            low: +k.l,
            close: +k.c,
            volume: +k.v,
          }
          push({ price: bar.close, changePercent: null, bar, source: 'binance', at: Date.now() })
        }
        ws.onclose = () => {
          if (!closed) retry = window.setTimeout(connect, 3000)
        }
      }
      connect()
      return () => {
        closed = true
        window.clearTimeout(retry)
        ws?.close()
      }
    }
    const es = new EventSource(`/api/v1/trade/stream?symbols=${encodeURIComponent(`${market}:${symbol}`)}&every=5`)
    es.onmessage = (ev) => {
      const q = JSON.parse(ev.data)
      if (typeof q.price === 'number')
        push({ price: q.price, changePercent: q.change_percent ?? null, bar: null, source: 'server', at: Date.now() })
    }
    return () => es.close()
  }, [symbol, market, interval, enabled]) // eslint-disable-line react-hooks/exhaustive-deps

  return tick
}
