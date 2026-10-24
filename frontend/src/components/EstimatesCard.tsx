import { useEffect, useState } from 'react'
import { getEstimates, type Estimates } from '../api/compare'
import { cx } from '../lib/cx'
import { compact, errorMessage, num, pct, trendClass } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

const MOMENTUM = {
  rising: { text: 'Estimates rising', className: 'bg-up-soft text-up' },
  falling: { text: 'Estimates falling', className: 'bg-down-soft text-down' },
  steady: { text: 'Estimates steady', className: 'bg-raised text-muted' },
}

/** Consensus EPS / revenue by period, how the consensus moved, and recent beats or misses. */
export default function EstimatesCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Estimates | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getEstimates(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto' || (data && !data.available)) return null
  const m = data?.momentum ? MOMENTUM[data.momentum.label] : null
  const cur = data?.currency ? `${data.currency} ` : ''

  return (
    <Card id="section-estimates" section="Estimates">
      <CardHeader
        title="Analyst estimates"
        description="Consensus forecasts and how they have moved"
        icon="analyze"
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-sm text-muted">Estimates unavailable: {error}</p>
        ) : !data ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            {(m || data?.beats) && (
            <div className="flex flex-wrap gap-1.5">
              {m && data?.momentum && (
                <span className={cx('rounded-md px-2 py-0.5 text-xs', m.className)} title="Average change in the current- and next-year EPS consensus over 90 days">
                  {m.text} {pct(data.momentum.change_90d, 1)} / 90d
                </span>
              )}
              {data?.beats && (
                <span className="rounded-md bg-raised px-2 py-0.5 text-xs text-muted">
                  Beat {data.beats.beat} of last {data.beats.total}
                </span>
              )}
            </div>
          )}
            {data.periods.length > 0 && (
              <div className="overflow-x-auto">
                <table className="tabular w-full min-w-[34rem] text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="py-2 text-start font-medium">Period</th>
                      <th className="px-2 py-2 text-end font-medium">EPS (range)</th>
                      <th className="px-2 py-2 text-end font-medium">vs year ago</th>
                      <th className="px-2 py-2 text-end font-medium" title="Change in the EPS consensus over 90 days">90d revision</th>
                      <th className="px-2 py-2 text-end font-medium" title="Analysts raising / cutting their EPS estimate in the last 30 days">Up / down 30d</th>
                      <th className="px-2 py-2 text-end font-medium">Revenue</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.periods.map((p) => (
                      <tr key={p.key}>
                        <td className="py-2">
                          {p.label}
                          {p.eps.analysts != null && <span className="text-xs text-faint"> · {num(p.eps.analysts, 0)}</span>}
                        </td>
                        <td className="px-2 py-2 text-end">
                          {num(p.eps.avg)}
                          {p.eps.low != null && p.eps.high != null && (
                            <span className="block text-[11px] text-faint">{num(p.eps.low)}–{num(p.eps.high)}</span>
                          )}
                        </td>
                        <td className={cx('px-2 py-2 text-end', trendClass(p.eps.growth))}>{pct(p.eps.growth, 1)}</td>
                        <td className={cx('px-2 py-2 text-end', trendClass(p.trend.change_90d))}>{pct(p.trend.change_90d, 1)}</td>
                        <td className="px-2 py-2 text-end">
                          <span className="text-up">{num(p.revisions.up_30d, 0)}</span>
                          <span className="text-faint"> / </span>
                          <span className="text-down">{num(p.revisions.down_30d, 0)}</span>
                        </td>
                        <td className="px-2 py-2 text-end">
                          {p.revenue.avg != null ? `${cur}${compact(p.revenue.avg)}` : '—'}
                          {p.revenue.growth != null && (
                            <span className={cx('block text-[11px]', trendClass(p.revenue.growth))}>{pct(p.revenue.growth, 1)}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {data.history.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-muted">Recent quarters: actual vs expected EPS</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {data.history.map((h) => (
                    <div key={h.quarter} className="rounded-lg bg-canvas px-3 py-2 text-xs">
                      <div className="text-faint">{h.quarter}</div>
                      <div className="tabular mt-0.5 text-sm font-semibold">{num(h.actual)}</div>
                      <div className="tabular text-faint">
                        est {num(h.estimate)} ·{' '}
                        <span className={trendClass(h.surprise)}>{h.surprise == null ? '—' : `${h.surprise >= 0 ? 'beat' : 'miss'} ${pct(h.surprise, 1)}`}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <p className="text-[12px] text-faint">Source: consensus of third-party analysts. Coverage is thinner for smaller and non-US companies.</p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
