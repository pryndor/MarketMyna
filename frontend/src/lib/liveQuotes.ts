import { useEffect, useMemo, useRef, useState } from 'react'
import { apiClient } from '../api/client'

// Live prices for the rows on screen: asks the server every second (it
// answers from a shared cache that refreshes upstream every few seconds, see
// src/services/live_quotes.py) and merges the newest price into each row.
// Funds (NAV once a day) are left alone. Pauses while the tab is hidden.

type LiveQuote = {
  price: number
  change: number | null
  change_percent: number | null
  volume: number | null
  time: number
}

type MarketStatus = {
  open: boolean
  age_seconds: number | null
  source: string
  error: string | null
  last_trade: number | null
}

export type LiveStatus = {
  /** Per market on screen. */
  markets: Record<string, MarketStatus>
  /** Newest data age (seconds) across markets, for the badge. */
  updated: number | null
}

type Row = {
  symbol: string
  market: string
  type?: string
  price?: number | null
  change_percent?: number | null
  volume?: number | null
}

const POLL_MS = 1000
const FLASH_MS = 1200

const key = (market: string, symbol: string) => `${market}:${symbol.toUpperCase()}`

export function useLiveQuotes<T extends Row>(rows: T[], enabled = true) {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({})
  const [status, setStatus] = useState<LiveStatus>({ markets: {}, updated: null })
  // key -> (direction, until) for the green / red flash after a change.
  const [flashes, setFlashes] = useState<Record<string, { dir: 'up' | 'down'; until: number }>>({})
  const last = useRef<Record<string, number>>({})

  // Which symbols to ask for, grouped by market ("All markets" mixes them).
  const wanted = useMemo(() => {
    const byMarket: Record<string, string[]> = {}
    for (const r of rows) {
      if (r.type === 'mf' || !r.market || !r.symbol) continue
      ;(byMarket[r.market] ??= []).push(r.symbol)
    }
    return byMarket
  }, [rows])
  const signature = JSON.stringify(wanted)

  useEffect(() => {
    if (!enabled || !Object.keys(wanted).length) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function tick() {
      if (document.visibilityState === 'visible') {
        const results = await Promise.allSettled(
          Object.entries(wanted).map(([market, symbols]) =>
            apiClient
              .get<MarketStatus & { quotes: Record<string, LiveQuote> }>('/listings/live', {
                params: { market, symbols: symbols.join(',') },
              })
              .then((r) => ({ market, data: r.data })),
          ),
        )
        if (stopped) return
        const nextQuotes: Record<string, LiveQuote> = {}
        const markets: Record<string, MarketStatus> = {}
        const changed: Record<string, { dir: 'up' | 'down'; until: number }> = {}
        const now = Date.now()
        for (const res of results) {
          if (res.status !== 'fulfilled') continue
          const { market, data } = res.value
          markets[market] = {
            open: data.open,
            age_seconds: data.age_seconds,
            source: data.source,
            error: data.error,
            last_trade: data.last_trade,
          }
          for (const [sym, q] of Object.entries(data.quotes)) {
            const k = key(market, sym)
            nextQuotes[k] = q
            const before = last.current[k]
            if (before != null && q.price !== before)
              changed[k] = { dir: q.price > before ? 'up' : 'down', until: now + FLASH_MS }
            last.current[k] = q.price
          }
        }
        setQuotes((prev) => ({ ...prev, ...nextQuotes }))
        const ages = Object.values(markets)
          .map((m) => m.age_seconds)
          .filter((a): a is number => a != null)
        setStatus({ markets, updated: ages.length ? Math.min(...ages) : null })
        if (Object.keys(changed).length) setFlashes((prev) => ({ ...prev, ...changed }))
      }
      if (!stopped) timer = setTimeout(tick, POLL_MS)
    }
    tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, enabled])

  /** The rows with the newest price / change / volume merged in. */
  const merged = useMemo(
    () =>
      rows.map((r) => {
        const q = r.type === 'mf' ? undefined : quotes[key(r.market, r.symbol)]
        if (!q) return r
        return {
          ...r,
          price: q.price,
          change_percent: q.change_percent ?? r.change_percent,
          volume: q.volume ?? r.volume,
        }
      }),
    [rows, quotes],
  )

  /** "flash-up" / "flash-down" right after a row's price moved, else "". */
  function flash(r: Row): string {
    const f = flashes[key(r.market, r.symbol)]
    return f && f.until > Date.now() ? `flash-${f.dir}` : ''
  }

  return { rows: merged, status, flash }
}
