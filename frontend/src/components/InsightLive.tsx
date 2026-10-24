import { useEffect, useState } from 'react'
import type { LiveInfo } from '../api/listings'
import { cx } from '../lib/cx'

function ago(seconds: number): string {
  if (seconds < 5) return 'just now'
  if (seconds < 90) return `${Math.round(seconds)}s ago`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`
  return `${Math.round(seconds / 3600)} h ago`
}

/** One line under a Market insights header: "● Live · updated 12s ago" while
 * the market trades, "Market closed · last session's prices" after, or, for
 * views on daily data, when it was last checked. `at` = when the browser got
 * the data (ticks the age between refreshes). */
export default function InsightLive({
  live,
  at,
  daily,
  ticking,
}: {
  live?: LiveInfo | null
  at: number | null
  /** Age (s) of the per-second prices on screen, when the view has them. */
  ticking?: number | null
  /** For views without live prices: what updates and when, e.g. "New figures each evening". */
  daily?: string
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), live?.open ? 1000 : 15_000)
    return () => window.clearInterval(t)
  }, [live?.open])

  if (!live || !live.live) {
    if (!daily || at == null) return null
    return (
      <span className="text-[11px] text-faint">
        {daily} · checked {ago((now - at) / 1000)}
      </span>
    )
  }
  const ranked = live.age_seconds != null && at != null ? live.age_seconds + (now - at) / 1000 : null
  const age = ticking != null ? ticking : ranked
  return (
    <span
      className="inline-flex flex-wrap items-center gap-x-1.5 text-[11px] text-muted"
      title={`${live.source} · ${live.covered.toLocaleString()} priced live`}
    >
      <span className={cx('inline-flex items-center gap-1 font-medium', live.open ? 'text-up' : 'text-muted')}>
        <span className={cx('h-1.5 w-1.5 rounded-full', live.open ? 'animate-pulse bg-up' : 'bg-faint')} />
        {live.open ? 'Live' : 'Market closed'}
      </span>
      <span>
        {live.open ? `prices updated ${age == null ? '…' : ago(age)}` : "last session's prices"}
      </span>
      {live.error && <span className="text-warn">· {live.error}</span>}
    </span>
  )
}
