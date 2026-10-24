import { createContext, useContext, useEffect, useRef, useState, type DependencyList } from 'react'
import type { LiveInfo } from '../api/listings'
import { errorMessage } from './format'

// Keeps a Market insights view up to date: the first load shows the loader,
// later refreshes swap the data in place (no flicker), only while the view's
// tab is the one on screen and the browser tab is visible. A failed refresh
// keeps the last data and tries again on the next round.

/** False for the insight panels that stay mounted but hidden (MarketInsights). */
export const InsightActive = createContext(true)

/** Live views: every `fast` ms while the market trades, every 5 min when closed. */
export const liveEvery =
  (fast: number) =>
  (d: { live?: LiveInfo | null }): number =>
    d.live?.open ? fast : 5 * 60_000

/** Views on daily data (flows, deals, macro): look for a new day's numbers. */
export const DAILY_EVERY = 10 * 60_000

export function useInsight<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
  every: number | ((data: T) => number),
) {
  const active = useContext(InsightActive)
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** Client time of the last successful load. */
  const [at, setAt] = useState<number | null>(null)
  // Bumped after every refresh attempt, so the next one gets scheduled.
  const [round, setRound] = useState(0)
  const [reloads, setReloads] = useState(0)
  const loadRef = useRef(load)
  loadRef.current = load
  const everyRef = useRef(every)
  everyRef.current = every
  const tried = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError(null)
    setAt(null)
    loadRef.current(controller.signal)
      .then((d) => {
        setData(d)
        setAt(Date.now())
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloads])

  useEffect(() => {
    if (!active || data == null || at == null) return
    const e = everyRef.current
    const ms = typeof e === 'function' ? e(data) : e
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const run = async () => {
      if (document.visibilityState !== 'visible') {
        timer = setTimeout(run, 2000)
        return
      }
      tried.current = Date.now()
      try {
        const d = await loadRef.current(controller.signal)
        if (controller.signal.aborted) return
        setData(d)
        setAt(Date.now())
        setError(null)
      } catch {
        /* keep the last data; try again next round */
      }
      if (!controller.signal.aborted) setRound((n) => n + 1)
    }
    // Overdue (e.g. the tab was hidden for a while): refresh right away.
    // After a failed try, wait a full round from that try.
    timer = setTimeout(run, Math.max(0, Math.max(at, tried.current) + ms - Date.now()))
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, data == null, at, round])

  return { data, error, at, reload: () => setReloads((n) => n + 1) }
}

/** "flash-up" / "flash-down" for a key whose value just changed, else "". */
export function useFlash(values: Record<string, number | null | undefined>) {
  const last = useRef<Record<string, number>>({})
  const [flashes, setFlashes] = useState<Record<string, { dir: 'up' | 'down'; until: number }>>({})
  const signature = JSON.stringify(values)

  useEffect(() => {
    const now = Date.now()
    const changed: Record<string, { dir: 'up' | 'down'; until: number }> = {}
    for (const [k, v] of Object.entries(values)) {
      if (v == null) continue
      const before = last.current[k]
      if (before != null && before !== v) changed[k] = { dir: v > before ? 'up' : 'down', until: now + 1200 }
      last.current[k] = v
    }
    if (Object.keys(changed).length) setFlashes((f) => ({ ...f, ...changed }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature])

  return (key: string): string => {
    const f = flashes[key]
    return f && f.until > Date.now() ? `flash-${f.dir}` : ''
  }
}
