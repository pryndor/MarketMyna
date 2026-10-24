import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRotation, type Quadrant } from '../api/listings'
import { cx } from '../lib/cx'
import { pct, trendClass } from '../lib/format'
import { liveEvery, useFlash, useInsight } from '../lib/insight'
import { ScrollBox } from './ui'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'
import RotationChart, { ROTATION_COLORS as COLORS, rotationQuadrants } from './RotationChart'

const QUADRANTS = rotationQuadrants('index')
const PHASE_RANK: Record<Quadrant, number> = { lagging: 0, weakening: 1, improving: 2, leading: 3 }

/** Relative rotation graph of sector baskets vs the market index. */
export default function SectorRotation({ market }: { market: string }) {
  // hover previews a sector; a click pins it (and lists its stocks) until
  // clicked again. The chart follows the hover first, then the pinned one.
  const [hover, setHover] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const focus = hover ?? picked
  useEffect(() => setPicked(null), [market])
  // The current week's point (and phase) moves with today's live prices.
  const { data, error, at } = useInsight((signal) => getRotation(market, signal), [market], liveEvery(30_000))
  // A phase change between refreshes flashes green (stronger) or red (weaker).
  const flash = useFlash(Object.fromEntries((data?.sectors ?? []).map((s) => [s.sector, PHASE_RANK[s.quadrant]])))


  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Sector rotation</h2>
          <p className="text-xs text-muted">
            {data
              ? `${market === 'crypto' ? 'Coin groups' : 'Sectors'} vs ${data.benchmark.name}, weekly to ${data.as_of}${data.live?.live ? ' (this week on live prices)' : ''} · click a sector to pin its ${data.sectors[0]?.tail.length ?? 0}-week trail`
              : 'Which sectors are gaining or losing strength against the index'}
          </p>
          {data && <InsightLive live={data.live} at={at} />}
        </div>
      </div>
      <div className="px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Loading weekly prices for sector baskets…', 'Comparing each sector with the index…', 'Placing sectors on the rotation chart…']} />}
        {data && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <RotationChart series={data.sectors.map((s) => ({ name: s.sector, tail: s.tail }))} focus={focus} />
            <div className="min-w-0">
              <ScrollBox maxHeight="36rem">
                <table className="w-full table-fixed text-sm">
                  <colgroup>
                    <col />
                    <col className="w-28" />
                    <col className="w-20" />
                  </colgroup>
                  <thead className="text-xs text-muted">
                    <tr>
                      <th className="py-1 pe-4 ps-2 text-start font-medium">Sector</th>
                      <th className="px-3 py-1 text-start font-medium">Phase</th>
                      <th className="py-1 pe-2 ps-3 text-end font-medium">4 weeks</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.sectors.map((s, i) => {
                      const selected = picked === s.sector
                      const toggle = () => setPicked(selected ? null : s.sector)
                      return (
                        <tr
                          key={s.sector}
                          tabIndex={0}
                          aria-selected={selected}
                          onClick={toggle}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              toggle()
                            }
                          }}
                          onMouseEnter={() => setHover(s.sector)}
                          onMouseLeave={() => setHover(null)}
                          title={selected ? 'Click again to unpin' : `Click to pin · basket: ${s.members.join(', ')}`}
                          className={cx(
                            'cursor-pointer transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent',
                            selected ? 'bg-accent-soft font-medium shadow-[inset_3px_0_0_var(--color-accent)]' : 'hover:bg-raised',
                          )}
                        >
                          <td className="truncate py-1.5 pe-4 ps-2">
                            <span
                              className={cx('me-2 inline-block rounded-full align-middle', selected ? 'h-2.5 w-2.5 ring-2 ring-fg/40' : 'h-2 w-2')}
                              style={{ backgroundColor: COLORS[i % COLORS.length] }}
                            />
                            {s.sector}
                          </td>
                          <td className={cx('truncate rounded px-3 py-1.5 text-xs', QUADRANTS[s.quadrant].className, flash(s.sector))} title={QUADRANTS[s.quadrant].note}>
                            {QUADRANTS[s.quadrant].label}
                          </td>
                          <td className={cx('tabular py-1.5 pe-2 ps-3 text-end', trendClass(s.return_4w))}>{pct(s.return_4w, 1)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </ScrollBox>
              {(() => {
                const sel = data.sectors.find((x) => x.sector === picked)
                if (!sel) return null
                return (
                  <div className="mt-3 rounded-lg border border-accent/40 bg-accent-soft px-3 py-2.5">
                    <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
                      <span className="font-medium text-fg">
                        {sel.sector} · <span className={QUADRANTS[sel.quadrant].className}>{QUADRANTS[sel.quadrant].label}</span>
                      </span>
                      <button type="button" onClick={() => setPicked(null)} className="text-muted hover:text-fg">
                        Unpin
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {sel.members.map((m) => (
                        <Link
                          key={m}
                          to={`/analyze?symbol=${encodeURIComponent(m)}&market=${market}`}
                          className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-xs hover:border-accent hover:text-accent-fg"
                        >
                          {m}
                        </Link>
                      ))}
                    </div>
                  </div>
                )
              })()}
              <p className="mt-2 text-xs text-faint">
                Right = stronger than the index, up = strength rising. Sectors usually cycle clockwise: improving → leading → weakening → lagging.
                Each sector is a cap-weighted basket of its largest stocks; click a row to pin its trail and see its stocks.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
