import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getEtfRotation, getFundRotation, type FundRotation as Data, type Quadrant } from '../api/listings'
import { cx } from '../lib/cx'
import { pct, trendClass } from '../lib/format'
import { DAILY_EVERY, liveEvery, useFlash, useInsight } from '../lib/insight'
import { ScrollBox, Segmented } from './ui'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'
import RotationChart, { ROTATION_COLORS as COLORS, rotationQuadrants as quadrants } from './RotationChart'

const VIEWS = [
  { value: 'category', label: 'Categories' },
  { value: 'amc', label: 'Fund houses' },
]
const MAX_DOTS = 15

const ETF_MARKETS = ['us', 'hong_kong', 'china_a']
const PHASE_RANK: Record<Quadrant, number> = { lagging: 0, weakening: 1, improving: 2, leading: 3 }

/** Relative rotation of equity mutual funds vs the Nifty 500 (India): by
 * category or fund house, and drill into one to see each of its funds.
 * For US / Hong Kong / China A it shows ETFs against their home market,
 * grouped into views (sectors, themes, ...). */
export default function FundRotation({ market = 'india' }: { market?: string } = {}) {
  const etf = ETF_MARKETS.includes(market)
  const [by, setBy] = useState<'category' | 'amc'>('category')
  const [group, setGroup] = useState<string | null>(null)
  const [view, setView] = useState<string | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  const [loadedFor, setLoadedFor] = useState(market)
  if (loadedFor !== market) {
    setLoadedFor(market)
    setView(null)
    setGroup(null)
  }
  // ETFs: the current week's point moves with live prices. Fund NAVs come
  // once a day, so the mutual fund view only looks for the new day's NAVs.
  const { data, error, at } = useInsight<Data>(
    (signal) => (etf ? getEtfRotation(market, view, signal) : getFundRotation(by, group, signal)),
    [etf, market, view, by, group],
    etf ? liveEvery(60_000) : DAILY_EVERY,
  )
  const QUADRANTS = quadrants(data?.benchmark.name ?? (etf ? 'market' : 'Nifty 500'))
  const flash = useFlash(Object.fromEntries((data?.items ?? []).map((s) => [s.name, PHASE_RANK[s.quadrant]])))

  const items = data?.items ?? []
  const shown = items.slice(0, Math.max(MAX_DOTS, items.length))

  const counts = useMemo(() => {
    const c: Record<Quadrant, number> = { leading: 0, improving: 0, weakening: 0, lagging: 0 }
    for (const s of items) c[s.quadrant] += 1
    return c
  }, [items])

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">
            {group ? (
              <>
                <button type="button" onClick={() => setGroup(null)} className="me-2 text-accent-fg hover:underline">
                  ← {by === 'amc' ? 'All fund houses' : 'All categories'}
                </button>
                {group}
              </>
            ) : etf ? (
              'ETF rotation'
            ) : (
              'Mutual fund rotation'
            )}
          </h2>
          <p className="text-xs text-muted">
            {etf
              ? data
                ? `${data.group} ETFs vs the ${data.benchmark.name}, weekly to ${data.as_of}.`
                : 'Which sector, theme, style and country ETFs are leading, weakening, lagging or improving'
              : data
              ? `Equity funds (Direct, Growth) vs the ${data.benchmark.name}, weekly to ${data.as_of}. ${group ? 'Each fund on its own.' : 'Click a row to see its funds.'}`
              : 'Which fund categories and fund houses are leading, weakening, lagging or improving'}
          </p>
          {data && <InsightLive live={data.live} at={at} daily={etf ? undefined : 'Fund NAVs update once a day'} />}
        </div>
        {etf
          ? data?.groups && data.groups.length > 1 && (
              <Segmented
                size="sm"
                options={data.groups.map((g) => ({ value: g, label: g }))}
                value={data.group ?? data.groups[0]}
                onChange={(v) => setView(v)}
              />
            )
          : !group && <Segmented size="sm" options={VIEWS} value={by} onChange={(v) => setBy(v as 'category' | 'amc')} />}
      </div>
      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && (
          <div className="space-y-2">
            <InsightLoader
              className="min-h-56"
              steps={
                etf
                  ? ['Loading two years of ETF prices…', 'Comparing each ETF with its home market…', 'Placing ETFs on the rotation chart…']
                  : ['Reading weekly NAVs for a few hundred funds…', 'Building baskets by category…', 'Comparing each basket with the Nifty 500…', 'Placing groups on the rotation chart…']
              }
            />
            {!etf && <p className="text-xs text-faint">Reading weekly NAVs for a few hundred funds; the first load can take half a minute.</p>}
          </div>
        )}
        {data && (
          <>
            <div className="flex flex-wrap gap-2 text-xs">
              {(Object.keys(QUADRANTS) as Quadrant[]).map((q) => (
                <span key={q} className={cx('rounded-full border border-line px-2.5 py-0.5', QUADRANTS[q].className)} title={QUADRANTS[q].note}>
                  {QUADRANTS[q].label} · {counts[q]}
                </span>
              ))}
            </div>
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <RotationChart series={shown} focus={focus} />
              <div className="min-w-0">
                <ScrollBox maxHeight="30rem">
                  <table className="w-full table-fixed text-sm">
                    <colgroup>
                      <col />
                      <col className="w-24" />
                      <col className="w-16" />
                    </colgroup>
                    <thead className="sticky top-0 bg-surface text-xs text-muted">
                      <tr>
                        <th className="py-1 text-start font-medium">{etf ? 'ETF' : group ? 'Fund' : by === 'amc' ? 'Fund house' : 'Category'}</th>
                        <th className="py-1 text-start font-medium">Phase</th>
                        <th className="py-1 text-end font-medium">4 weeks</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {items.map((s, i) => (
                        <tr
                          key={s.code ?? s.name}
                          onMouseEnter={() => setFocus(s.name)}
                          onMouseLeave={() => setFocus(null)}
                          onClick={() => !etf && !group && setGroup(s.name)}
                          title={etf ? s.code : group ? `${s.amc ?? ''} · ${s.category ?? ''}` : `Basket of ${s.funds} of ${s.total_funds} funds · click to see each fund`}
                          className={cx('hover:bg-raised', !etf && !group && 'cursor-pointer')}
                        >
                          <td className="truncate py-1.5 pe-2" title={s.name}>
                            <span className="me-2 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                            {etf && s.symbol ? (
                              <Link to={`/analyze?symbol=${encodeURIComponent(s.symbol)}&market=${market}`} className="hover:text-accent-fg">
                                <span className="font-mono text-xs text-muted">{s.code}</span> {s.name}
                              </Link>
                            ) : group && s.code ? (
                              <Link to={`/?market=india&type=mf&q=${encodeURIComponent(s.name)}`} className="hover:text-accent-fg">
                                {s.name}
                              </Link>
                            ) : (
                              s.name
                            )}
                          </td>
                          <td className={cx('rounded py-1.5 pe-2 text-xs', QUADRANTS[s.quadrant].className, flash(s.name))} title={QUADRANTS[s.quadrant].note}>
                            {QUADRANTS[s.quadrant].label}
                          </td>
                          <td className={cx('tabular py-1.5 text-end', trendClass(s.return_4w))}>{pct(s.return_4w, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollBox>
                <p className="mt-2 text-xs text-faint">
                  Right = stronger than the {data.benchmark.name}, up = strength rising; {etf ? 'ETFs' : 'funds'} usually cycle clockwise: improving → leading →
                  weakening → lagging.{' '}
                  {etf ? 'Click an ETF to analyse it.' : group ? 'Click a fund to find it in the list.' : 'Groups are equal-weighted baskets of their longest-running funds.'} Past relative
                  performance; not a recommendation.
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
