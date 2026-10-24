import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getDividends, type Dividends } from '../api/compare'
import { num, pct } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

/** Dividend payments, yearly totals, yield and growth; hidden for non-payers. */
export default function DividendsCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Dividends | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setFailed(false)
    getDividends(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (failed || market === 'crypto' || (data && !data.pays)) return null
  if (!data) return <Skeleton className="h-40 w-full" />
  const cur = data.currency ? `${data.currency} ` : ''

  const stats: Array<[string, string, string?]> = [
    ['Trailing yield', data.ttm_yield != null ? `${num(data.ttm_yield, 2)}%` : '—', `${cur}${num(data.ttm)} paid in the last 12 months`],
    ['Forward yield', data.forward_yield != null ? `${num(data.forward_yield, 2)}%` : '—', data.forward_rate != null ? `${cur}${num(data.forward_rate)} a year at the current rate` : undefined],
    ['5-year growth', data.growth_5y != null ? pct(data.growth_5y, 1) : '—', 'Yearly dividend, compound'],
    ['Years without a cut', String(data.years_without_cut ?? '—'), data.first_year ? `Paying since ${data.first_year}` : undefined],
    ['Payout ratio', data.payout_ratio != null ? `${num(data.payout_ratio, 0)}%` : '—', 'Share of profit paid out'],
    ['How often', data.frequency ?? '—', data.next_ex_date ? `Next ex-date ${data.next_ex_date}` : data.last ? `Last ${data.last.date}` : undefined],
  ]

  return (
    <Card id="section-dividends" section="Dividends">
      <CardHeader title="Dividends" description="Payment history and how the payout has grown" icon="portfolio" />
      <CardBody className="space-y-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {stats.map(([label, value, sub]) => (
            <div key={label}>
              <div className="text-xs text-faint">{label}</div>
              <div className="tabular font-semibold">{value}</div>
              {sub && <div className="text-xs text-muted">{sub}</div>}
            </div>
          ))}
        </div>
        {data.years && data.years.length > 1 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Dividends per share by year ({data.currency})</div>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.years} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <XAxis dataKey="year" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis width={40} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={{ fill: 'var(--color-raised)' }}
                    contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                    formatter={(v, _n, item) => [`${cur}${num(Number(v))}${(item?.payload as { partial?: boolean })?.partial ? ' (so far)' : ''}`, 'Dividends']}
                  />
                  <Bar dataKey="total" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {data.years.map((y) => (
                      <Cell key={y.year} fill="var(--color-accent)" fillOpacity={y.partial ? 0.4 : 0.85} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        {data.payments && data.payments.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-xs text-muted">Recent payments</summary>
            <div className="mt-2 grid grid-cols-2 gap-x-6 sm:grid-cols-4">
              {data.payments.map((p) => (
                <div key={p.date} className="flex justify-between border-b border-line py-1 text-xs">
                  <span className="text-muted">{p.date}</span>
                  <span className="tabular">{num(p.amount, 2)}</span>
                </div>
              ))}
            </div>
          </details>
        )}
        <p className="text-[12px] text-faint">Ex-dividend dates, adjusted for splits and bonus issues. Source: market data feed. Faded bar = current year so far.</p>
      </CardBody>
    </Card>
  )
}
