import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getFundHistory, searchListings, type Listing, type NavPoint } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num, pct, price } from '../lib/format'
import { Segmented, Skeleton, Stat } from './ui'
import FundAiReview from './FundAiReview'
import FundAnalytics from './FundAnalytics'
import FundCostTax from './FundCostTax'
import FundHoldings from './FundHoldings'
import FundOverlap from './FundOverlap'
import FundStyle from './FundStyle'
import FundPeers from './FundPeers'
import SipPlanner from './SipPlanner'

const RANGES = [
  { value: '30', label: '1M' },
  { value: '182', label: '6M' },
  { value: '365', label: '1Y' },
  { value: '1095', label: '3Y' },
  { value: '1825', label: '5Y' },
  { value: 'all', label: 'Max' },
]

const DAY = 86_400_000

/** Point-to-point return over `days`; annualised (CAGR) beyond one year. */
function trailingReturn(points: Array<{ t: number; nav: number }>, days: number): number | null {
  if (points.length < 2) return null
  const last = points[points.length - 1]
  const cutoff = last.t - days * DAY
  const start = points.find((p) => p.t >= cutoff)
  if (!start || start === last || last.t - points[0].t < days * DAY * 0.95) return null
  const ratio = last.nav / start.nav
  return days > 365 ? (Math.pow(ratio, 365 / days) - 1) * 100 : (ratio - 1) * 100
}

/** The listing row for a scheme code (to open a competitor). */
export async function findFund(code: string): Promise<Listing | null> {
  const rows = await searchListings(code, 'india', 'mf', 5)
  return rows.find((r) => r.symbol === code) ?? null
}

/** Everything about one fund: returns, NAV chart, what it holds, how it
 * compares with its competitors, and SIP planning. Used by the side panel
 * and by the Analyze page. */
export function FundDetails({ fund, onOpenFund }: { fund: Listing; onOpenFund?: (code: string) => void }) {
  const [history, setHistory] = useState<NavPoint[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState('1095')

  useEffect(() => {
    let cancelled = false
    setHistory(null)
    setError(null)
    getFundHistory(fund.symbol)
      .then((rows) => !cancelled && setHistory(rows))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [fund.symbol])

  const all = useMemo(() => (history ?? []).map((p) => ({ t: new Date(p.date).getTime(), nav: p.nav })), [history])
  const points = useMemo(() => {
    if (range === 'all' || !all.length) return all
    const cutoff = all[all.length - 1].t - Number(range) * DAY
    return all.filter((p) => p.t >= cutoff)
  }, [all, range])

  const returns = [
    { label: '1M', days: 30 },
    { label: '6M', days: 182 },
    { label: '1Y', days: 365 },
    { label: '3Y CAGR', days: 1095 },
    { label: '5Y CAGR', days: 1825 },
  ].map((r) => ({ ...r, value: trailingReturn(all, r.days) }))

  const up = points.length < 2 || points[points.length - 1].nav >= points[0].nav
  const stroke = up ? 'var(--color-up)' : 'var(--color-down)'

  return (
        <div className="space-y-6">
          <div id="fund-overview" data-section="Overview" className="scroll-mt-6 space-y-6">
            {fund.shariah && fund.shariah_reason && (
              <div
                className={cx(
                  'rounded-lg px-3 py-2 text-xs',
                  fund.shariah === 'halal' ? 'bg-up-soft text-up' : fund.shariah === 'doubtful' ? 'bg-warn-soft text-warn' : 'bg-raised text-muted',
                )}
              >
                <span className="font-semibold">
                  {fund.shariah === 'halal' ? 'Ethical' : fund.shariah === 'doubtful' ? 'Ethical: doubtful' : 'Not ethical'}
                </span>{' '}
                · {fund.shariah_reason}
              </div>
            )}
            <div className="grid grid-cols-2 gap-5 sm:grid-cols-3">
              <Stat label="NAV" value={price(fund.price, fund.currency)} sub={fund.nav_date ? `as of ${fund.nav_date}` : undefined} />
              <Stat label="Plan" value={fund.plan ?? '—'} sub={fund.option ?? undefined} />
              <Stat label="Scheme code" value={<span className="font-mono">{fund.symbol}</span>} sub={fund.isin ?? undefined} />
            </div>
          </div>

          <div id="fund-returns" data-section="Returns & NAV" className="scroll-mt-6 space-y-6">
            <div className="grid grid-cols-3 gap-3 rounded-lg bg-canvas p-4 sm:grid-cols-5">
              {returns.map((r) => (
                <div key={r.label}>
                  <div className="text-xs text-faint">{r.label}</div>
                  {history == null && !error ? (
                    <Skeleton className="mt-1 h-4 w-12" />
                  ) : (
                    <div className={`tabular mt-0.5 text-sm font-semibold ${r.value == null ? 'text-faint' : r.value >= 0 ? 'text-up' : 'text-down'}`}>
                      {pct(r.value)}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div>
              <div className="mb-3 flex justify-end">
                <Segmented options={RANGES} value={range} onChange={setRange} size="sm" />
              </div>
              <div className="h-64">
                {error ? (
                  <div className="grid h-full place-items-center text-xs text-muted">NAV history unavailable: {error}</div>
                ) : history == null ? (
                  <Skeleton className="h-full w-full" />
                ) : points.length < 2 ? (
                  <div className="grid h-full place-items-center text-xs text-muted">Not enough NAV history for this range.</div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                      <defs>
                        <linearGradient id="navFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={stroke} stopOpacity={0.25} />
                          <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="var(--color-line)" vertical={false} />
                      <XAxis
                        dataKey="t"
                        type="number"
                        domain={['dataMin', 'dataMax']}
                        scale="time"
                        tickFormatter={(t: number) => new Date(t).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })}
                        tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        minTickGap={40}
                      />
                      <YAxis
                        domain={['auto', 'auto']}
                        orientation="right"
                        width={56}
                        tickFormatter={(v: number) => num(v)}
                        tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        cursor={{ stroke: 'var(--color-line-strong)' }}
                        contentStyle={{
                          background: 'var(--color-raised)',
                          border: '1px solid var(--color-line-strong)',
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                        labelFormatter={(t) => new Date(Number(t)).toLocaleDateString()}
                        formatter={(v) => [num(Number(v), 4), 'NAV']}
                      />
                      <Area type="monotone" dataKey="nav" stroke={stroke} strokeWidth={1.75} fill="url(#navFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
              <p className="mt-2 text-xs text-faint">NAV history from official fund data. Returns are point-to-point; 3Y/5Y annualised.</p>
            </div>
          </div>

          <FundAiReview code={fund.symbol} />

          <FundAnalytics code={fund.symbol} />

          <div id="fund-holdings" data-section="Holdings & sectors" className="scroll-mt-6 border-t border-line pt-6">
            <FundHoldings code={fund.symbol} />
            <div className="mt-6 border-t border-line pt-6">
              <FundOverlap code={fund.symbol} scheme={fund.name} />
            </div>
          </div>

          <FundStyle code={fund.symbol} />

          <div id="fund-competitors" data-section="Competitors" className="scroll-mt-6 border-t border-line pt-6">
            <FundPeers code={fund.symbol} onOpen={onOpenFund ? (code) => onOpenFund(code) : undefined} />
          </div>

          <FundCostTax code={fund.symbol} />

          <div id="fund-sip" data-section="SIP planner" className="scroll-mt-6">
            <SipPlanner code={fund.symbol} />
          </div>
        </div>
  )
}
