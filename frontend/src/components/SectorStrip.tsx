import { useEffect, useState } from 'react'
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import { getDiscovery, getRotation, searchListings, type RotationSector, type SectorMove } from '../api/listings'
import { cx } from '../lib/cx'
import { num, pct, trendClass } from '../lib/format'
import { rotationQuadrants } from './RotationChart'

// This stock's sector from Market pulse (today's move, breadth) and Sector
// rotation (weekly strength against the index), as one line and a small
// chart under the quote. Same sector baskets as the Markets page (the
// listings' broad category).

const MARKETS = ['india', 'us', 'china_a', 'hong_kong', 'crypto']

type Data = { sector: RotationSector; today: SectorMove | null; bench: string; asOf: string }

export default function SectorStrip({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Data | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    if (!MARKETS.includes(market)) return
    const base = symbol.replace(/\.(NS|BO)$/i, '').toUpperCase()
    Promise.all([
      getRotation(market),
      getDiscovery(market, 500).catch(() => null),
      market === 'crypto' ? Promise.resolve([]) : searchListings(base, market, 'all', 5).catch(() => []),
    ])
      .then(([rotation, pulse, rows]) => {
        const category = rows.find((r) => r.symbol.toUpperCase() === base)?.category
        // Crypto groups (and any stock missing a category) are found by membership.
        const sector =
          rotation.sectors.find((s) => category && s.sector === category) ??
          rotation.sectors.find((s) => s.members.some((m) => m.toUpperCase() === base))
        if (cancelled || !sector || sector.tail.length < 2) return
        setData({
          sector,
          today: pulse?.sectors.find((s) => s.sector === sector.sector) ?? null,
          bench: rotation.benchmark.name,
          asOf: rotation.as_of,
        })
      })
      .catch(() => undefined) // no rotation for this market right now: no strip
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (!data) return null
  const { sector, today, bench } = data
  const quad = rotationQuadrants(bench)[sector.quadrant]
  const points = sector.tail.map((p) => ({ week: p.week, strength: p.ratio }))

  return (
    <div className="mb-5 rounded-lg bg-canvas px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        <span className="text-muted">
          Sector <span className="font-semibold text-fg">{sector.sector}</span>
        </span>
        <span className={cx('font-semibold', quad.className)} title={quad.note}>
          {quad.label}
        </span>
        <span className="text-muted">
          Today{' '}
          <span className={cx('tabular font-semibold', trendClass(today?.change_percent))}>
            {today?.change_percent != null ? pct(today.change_percent) : '—'}
          </span>
          {today && <span className="text-faint"> · {today.advancers} up, {today.decliners} down</span>}
        </span>
        <span className="text-muted">
          4 weeks{' '}
          <span className={cx('tabular font-semibold', trendClass(sector.return_4w))}>
            {sector.return_4w != null ? pct(sector.return_4w) : '—'}
          </span>
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-3">
        <div className="h-12 min-w-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
              <YAxis hide domain={['auto', 'auto']} />
              <ReferenceLine y={100} stroke="var(--color-line-strong)" strokeDasharray="4 4" />
              <Tooltip
                formatter={(v) => [num(Number(v), 1), 'Strength vs index']}
                labelFormatter={(_, p) => (p?.[0]?.payload as { week?: string } | undefined)?.week ?? ''}
                contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
              />
              <Line type="monotone" dataKey="strength" stroke="var(--color-accent)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="shrink-0 text-end">
          <div className={cx('tabular text-sm font-semibold', trendClass(sector.ratio - 100))}>{num(sector.ratio, 1)}</div>
          <div className="text-[11px] text-faint">vs {bench} (100)</div>
        </div>
      </div>
      <p className="mt-1 text-[11px] text-faint">
        The sector's weekly strength against the {bench}, up to {data.asOf}: above the dashed line it is beating the
        index. A description of the sector, not advice.
      </p>
    </div>
  )
}
