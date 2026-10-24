import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getSipDays, type SipDays, type SipEdge } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'
import InsightLoader from './InsightLoader'

// Historically best SIP day (src/services/sip_days.py): a table badge for the
// Markets list and a card with every day 1-28 for a fund or ETF page. Worded
// as past behaviour, never a recommendation.

const EDGE: Record<SipEdge, { label: string; className: string; hint: string }> = {
  consistent: {
    label: 'Consistent',
    className: 'bg-up-soft text-up',
    hint: 'The best day landed within a few days of each other over 3, 5 and 10 years',
  },
  no_edge: {
    label: 'No reliable edge',
    className: 'bg-raised text-muted',
    hint: 'The best day moved around between periods, so any day is about as good',
  },
  negligible: {
    label: 'Gap too small',
    className: 'bg-raised text-muted',
    hint: 'Best and worst day differ by under 0.1 points a year, so the day makes no real difference',
  },
  short: {
    label: 'Under 5 years',
    className: 'bg-warn-soft text-warn',
    hint: 'Only 3-5 years of prices, too short to check whether the day holds up',
  },
}

export function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'
  return `${n}${s}`
}

/** Compact "12th · Consistent" for the Markets table. */
export function SipDayBadge({ day, edge, spread }: { day?: number; edge?: SipEdge; spread?: number }) {
  if (!day || !edge) return <span className="text-xs text-faint">—</span>
  const e = EDGE[edge]
  return (
    <span
      className="inline-flex items-center justify-end gap-1.5 whitespace-nowrap text-xs"
      title={`${e.hint}. Best beat worst by ${spread?.toFixed(2) ?? '?'} points a year. Past behaviour, not advice.`}
    >
      <span className="tabular font-medium">{ordinal(day)}</span>
      <span className={cx('rounded px-1 text-[11px] font-medium', e.className)}>{edge === 'consistent' ? '✓' : edge === 'short' ? '<5y' : edge === 'negligible' ? '~0' : '≈'}</span>
    </span>
  )
}

/** Full card: best day, label, 3/5/10-year table and the 28-day XIRR chart. */
export function SipDayCard({
  market,
  kind,
  symbol,
  highlight,
}: {
  market: string
  kind: 'mf' | 'etf'
  symbol: string
  /** The SIP day the user picked elsewhere, outlined on the chart. */
  highlight?: number
}) {
  const [data, setData] = useState<SipDays | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getSipDays(market, kind, symbol)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(errorMessage(e)))
    return () => {
      cancelled = true
    }
  }, [market, kind, symbol])

  const s = data?.summary
  const valid = (data?.curve ?? []).filter((c) => c.xirr_pct != null) as Array<{ day: number; xirr_pct: number }>
  const best = valid.length ? valid.reduce((a, b) => (b.xirr_pct > a.xirr_pct ? b : a)) : null
  const worst = valid.length ? valid.reduce((a, b) => (b.xirr_pct < a.xirr_pct ? b : a)) : null
  const lo = worst ? worst.xirr_pct : 0
  const hi = best ? best.xirr_pct : 0
  const pad = Math.max((hi - lo) * 0.25, 0.02)

  return (
    <div className="rounded-lg border border-line p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">Historically best SIP day</div>
          <div className="text-xs text-muted">A monthly SIP replayed on every day 1–28, ranked by XIRR</div>
        </div>
        {s && (
          <div className="flex items-center gap-2">
            <span className="tabular text-2xl font-semibold">{ordinal(s.best_day)}</span>
            <span className={cx('rounded-md px-2 py-0.5 text-xs font-medium', EDGE[s.edge].className)} title={EDGE[s.edge].hint}>
              {EDGE[s.edge].label}
            </span>
          </div>
        )}
      </div>

      {error && <p className="text-sm text-down">{error}</p>}
      {!data && !error && (
        <InsightLoader
          className="min-h-48"
          steps={['Downloading the full price history…', 'Replaying a SIP on every day 1–28…', 'Checking 3, 5 and 10 years…']}
        />
      )}
      {data && !s && <p className="text-sm text-muted">{data.note ?? 'Not enough price history yet.'}</p>}

      {s && (
        <div className="space-y-3">
          <table className="tabular w-full whitespace-nowrap text-xs">
            <thead className="text-muted">
              <tr>
                <th className="py-1 text-start font-medium">Period</th>
                <th className="py-1 text-end font-medium">
                  Best<span className="hidden sm:inline"> day</span>
                </th>
                <th className="py-1 text-end font-medium">
                  Worst<span className="hidden sm:inline"> day</span>
                </th>
                <th className="py-1 text-end font-medium">
                  <span className="hidden sm:inline">Best </span>XIRR
                </th>
                <th className="py-1 text-end font-medium" title="Best day's XIRR minus the worst day's, in points a year">Gap</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {Object.entries(s.windows).map(([k, w]) => (
                <tr key={k}>
                  <td className="py-1.5 pe-2">{k.replace('y', ' yrs')}</td>
                  <td className="py-1.5 text-end font-medium text-up">{ordinal(w.best)}</td>
                  <td className="py-1.5 text-end text-down">{ordinal(w.worst)}</td>
                  <td className="py-1.5 text-end">{w.best_xirr.toFixed(2)}%</td>
                  <td className="py-1.5 text-end text-muted">{w.spread.toFixed(2)} pts</td>
                </tr>
              ))}
            </tbody>
          </table>

          {valid.length > 0 && (
            <div>
              <div className="mb-1 text-xs text-muted">XIRR by SIP day, last {data!.years} years</div>
              <div className="h-36">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={valid} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                    <XAxis dataKey="day" tick={{ fontSize: 10 }} interval={2} tickLine={false} axisLine={false} />
                    <YAxis
                      domain={[lo - pad, hi + pad]}
                      tick={{ fontSize: 10 }}
                      width={50}
                      tickFormatter={(v) => `${Number(v).toFixed(hi - lo < 1 ? 2 : 1)}%`}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: 'var(--color-raised)' }}
                      contentStyle={{
                        background: 'var(--color-surface)',
                        border: '1px solid var(--color-line)',
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                      labelFormatter={(d) => `SIP on the ${ordinal(Number(d))}`}
                      formatter={(v) => [`${Number(v).toFixed(2)}% a year`, 'XIRR']}
                    />
                    {highlight && <ReferenceLine x={highlight} stroke="var(--color-accent)" strokeDasharray="3 3" />}
                    <Bar dataKey="xirr_pct" radius={[3, 3, 0, 0]}>
                      {valid.map((c) => (
                        <Cell
                          key={c.day}
                          fill={
                            c.day === best?.day ? 'var(--color-up)' : c.day === worst?.day ? 'var(--color-down)' : 'var(--color-line-strong)'
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          <p className="text-xs text-faint">
            {s.edge === 'consistent'
              ? `The ${ordinal(s.best_day)} (or a day close to it) came out best over every period checked. `
              : s.edge === 'negligible'
                ? 'Every day gave almost exactly the same return. '
                : s.edge === 'no_edge'
                ? 'The best day changed from one period to the next, so it looks like chance. '
                : 'Too little history to tell whether the best day holds up. '}
            The gap between best and worst is {s.spread.toFixed(2)} points a year over the longest period: pick the
            day that suits your salary. Buys on the first trading day on or after the chosen date
            {kind === 'etf' ? '; ETF prices adjusted for dividends and splits' : ''}. Past behaviour, as of {s.as_of};
            not investment advice.
          </p>
        </div>
      )}
    </div>
  )
}
