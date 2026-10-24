import { useEffect, useState } from 'react'
import { getFundInsights, type FundInsights as Insights } from '../api/portfolio'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

const BAR_COLORS = ['#6d8cff', '#34d399', '#fbbf24', '#f472b6', '#22d3ee', '#a78bfa', '#fb923c', '#94a3b8']

/** Mutual fund health check: asset mix, category duplicates, similar-moving funds, plan costs. */
export default function FundInsights({ portfolio, version }: { portfolio: string; version: string }) {
  const [data, setData] = useState<Insights | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    getFundInsights(portfolio)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [portfolio, version])

  const tone = data?.grade === 'Good' ? 'text-up' : data?.grade === 'Fair' ? 'text-warn' : 'text-down'

  return (
    <Card id="section-fund-health" section="Fund health check">
      <CardHeader title="Mutual fund health check" description="Mix, duplicate categories and funds that move together" icon="portfolio" />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-sm text-down">{error}</p>
        ) : !data ? (
          <Skeleton className="h-32 w-full" />
        ) : data.funds === 0 ? (
          <p className="text-sm text-muted">No mutual funds in this portfolio.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
              <div>
                <div className="text-xs text-faint">Score</div>
                <div className="tabular text-2xl font-semibold">
                  {data.score}
                  <span className="text-sm text-faint">/100</span> <span className={cx('text-sm', tone)}>{data.grade}</span>
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <div className="mb-1.5 text-xs text-faint">Asset mix</div>
                <div className="flex h-2.5 overflow-hidden rounded-full">
                  {data.asset_classes!.map((c, i) => (
                    <div key={c.name} title={`${c.name} ${num(c.weight * 100, 1)}%`} style={{ width: `${c.weight * 100}%`, background: BAR_COLORS[i % BAR_COLORS.length] }} />
                  ))}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                  {data.asset_classes!.map((c, i) => (
                    <span key={c.name} className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-sm" style={{ background: BAR_COLORS[i % BAR_COLORS.length] }} />
                      {c.name} <span className="tabular">{num(c.weight * 100, 0)}%</span>
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {data.issues!.length > 0 ? (
              <ul className="space-y-2">
                {data.issues!.map((t) => (
                  <li key={t} className="rounded-lg bg-canvas px-3 py-2 text-sm">{t}</li>
                ))}
              </ul>
            ) : (
              <p className="rounded-lg bg-up-soft px-3 py-2 text-sm text-up">No overlap or cost issues found.</p>
            )}

            <div className="grid gap-5 md:grid-cols-2">
              <div>
                <div className="mb-1.5 text-xs font-medium text-muted">By category</div>
                <table className="tabular w-full text-sm">
                  <tbody className="divide-y divide-line">
                    {data.categories!.map((c) => (
                      <tr key={c.name}>
                        <td className="py-1.5">{c.name}{c.count > 1 && <span className="text-warn"> ×{c.count}</span>}</td>
                        <td className="py-1.5 text-end">{num(c.weight * 100, 1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data.similar_pairs!.length > 0 && (
                <div>
                  <div className="mb-1.5 text-xs font-medium text-muted">Funds that move together (1y daily NAV)</div>
                  <table className="tabular w-full text-sm">
                    <tbody className="divide-y divide-line">
                      {data.similar_pairs!.map((p) => (
                        <tr key={`${p.a}-${p.b}`}>
                          <td className="py-1.5">{p.a_name} <span className="text-faint">&amp;</span> {p.b_name}</td>
                          <td className={cx('py-1.5 text-end', p.correlation >= 0.95 && 'text-warn')}>{num(p.correlation)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <p className="text-xs text-faint">{data.method} Not investment advice.</p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
