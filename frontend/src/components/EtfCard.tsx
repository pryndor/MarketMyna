import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getEtf, type EtfLookthrough } from '../api/compare'
import { compact, num } from '../lib/format'
import { SipDayCard } from './SipDays'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

const BAR = '#6d8cff'

function Bar({ label, weight, href, sub }: { label: string; weight: number; href?: string; sub?: string }) {
  const name = href ? <Link to={href} className="truncate hover:text-accent-fg">{label}</Link> : <span className="truncate">{label}</span>
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_5rem_3.25rem] items-center gap-2 py-1 text-sm">
      <span className="min-w-0 truncate" title={sub ? `${label} · ${sub}` : label}>{name}</span>
      <span className="h-2 rounded-full bg-raised">
        <span className="block h-2 rounded-full" style={{ width: `${Math.min(weight * 100 * 2.5, 100)}%`, background: BAR }} />
      </span>
      <span className="tabular text-end text-xs">{num(weight * 100, 1)}%</span>
    </div>
  )
}

/** What an ETF holds; renders nothing for stocks. */
export default function EtfCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<EtfLookthrough | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setFailed(false)
    getEtf(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (failed || market === 'crypto' || (data && !data.is_etf)) return null
  if (!data) return <Skeleton className="h-40 w-full" />

  const ok = data.status === 'ok'
  const desc = data.index ? `Tracks the ${data.index}` : [data.category, data.family].filter(Boolean).join(' · ') || 'Exchange-traded fund'

  return (
    <Card id="section-etf" section="ETF holdings">
      <CardHeader title="What this ETF holds" description={desc} icon="portfolio" />
      <CardBody className="space-y-5">
        {!ok ? (
          <p className="text-sm text-muted">{data.note}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {data.count != null && (
                <div>
                  <div className="text-xs text-faint">Holdings</div>
                  <div className="tabular font-semibold">{data.count}</div>
                </div>
              )}
              <div>
                <div className="text-xs text-faint">Top 10 weight</div>
                <div className="tabular font-semibold">{num((data.top10_weight ?? 0) * 100, 1)}%</div>
              </div>
              {data.expense_ratio != null && (
                <div title={data.category_expense_ratio != null ? `Category average ${num(data.category_expense_ratio * 100, 2)}%` : undefined}>
                  <div className="text-xs text-faint">Expense ratio</div>
                  <div className="tabular font-semibold">
                    {num(data.expense_ratio * 100, 2)}%
                    {data.category_expense_ratio != null && <span className="text-xs font-normal text-faint"> vs {num(data.category_expense_ratio * 100, 2)}%</span>}
                  </div>
                </div>
              )}
              {data.total_assets != null && (
                <div>
                  <div className="text-xs text-faint">Fund size</div>
                  <div className="tabular font-semibold">{compact(data.total_assets)}</div>
                </div>
              )}
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <div>
                <div className="mb-1 text-xs font-medium text-muted">Top holdings {data.weights === 'estimated' ? '(estimated weights)' : ''}</div>
                {data.top?.slice(0, 12).map((h) => (
                  <Bar key={h.symbol} label={h.name || h.symbol} sub={h.sector} weight={h.weight}
                    href={`/analyze?symbol=${encodeURIComponent(h.symbol)}&market=${market}`} />
                ))}
              </div>
              {data.sectors && data.sectors.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted">Sectors</div>
                  {data.sectors.slice(0, 12).map((s) => <Bar key={s.name} label={s.name} weight={s.weight} />)}
                </div>
              )}
            </div>
            <p className="text-[12px] text-faint">{data.note} Source: {data.source}. Use Compare to check overlap between two ETFs.</p>
          </>
        )}
        {['india', 'us', 'hong_kong'].includes(market) && <SipDayCard market={market} kind="etf" symbol={symbol} />}
      </CardBody>
    </Card>
  )
}
