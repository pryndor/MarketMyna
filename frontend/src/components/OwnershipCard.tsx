import { useEffect, useState } from 'react'
import { getOwnership, type DealsResponse, type Holder, type Ownership } from '../api/stocks'
import { cx } from '../lib/cx'
import { compact, errorMessage, num, pct } from '../lib/format'
import { Card, CardBody, CardHeader, Segmented, Skeleton } from './ui'

type Tab = 'insiders' | 'institutions' | 'funds' | 'deals'

/** Who owns the stock, what insiders are doing, and short interest (US). */
export default function OwnershipCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Ownership | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('insiders')

  useEffect(() => {
    let live = true
    setData(null)
    setError(null)
    getOwnership(symbol, market)
      .then((d) => live && setData(d))
      .catch((err) => live && setError(errorMessage(err)))
    return () => {
      live = false
    }
  }, [symbol, market])

  const b = data?.breakdown
  const ins = data?.insiders
  const tabs = [
    { value: 'insiders', label: `Insider trades${ins ? ` · ${ins.recent.length}` : ''}` },
    ...(data?.institutions.length ? [{ value: 'institutions', label: 'Institutions' }] : []),
    ...(data?.funds.length ? [{ value: 'funds', label: 'Funds' }] : []),
    ...(data?.deals ? [{ value: 'deals', label: `Bulk / block deals · ${data.deals.count}` }] : []),
  ]

  return (
    <Card id="section-ownership" section="Ownership">
      <CardHeader title="Ownership & insiders" description="Who holds the shares, and whether insiders are buying or selling" />
      <CardBody className="space-y-4">
        {error && <p className="text-sm text-muted">{error}</p>}
        {!data && !error && <Skeleton className="h-32 w-full" />}
        {data && b && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Mini label="Insiders / promoters" value={b.insiders_pct == null ? '—' : `${num(b.insiders_pct, 1)}%`} />
              <Mini label="Institutions" value={b.institutions_pct == null ? '—' : `${num(b.institutions_pct, 1)}%`} />
              <Mini label="Free float" value={compact(b.float_shares)} sub="shares" />
              <Mini
                label={`Insiders, ${ins?.days ?? 180}d`}
                value={ins?.bias ? (ins.bias === 'net buying' ? 'Net buying' : 'Net selling') : 'No trades'}
                className={ins?.bias === 'net buying' ? 'text-up' : ins?.bias === 'net selling' ? 'text-down' : undefined}
                sub={ins && (ins.buys || ins.sells) ? `${ins.buys} buys · ${ins.sells} sells` : undefined}
              />
            </div>

            {data.short && (
              <div className="rounded-lg bg-canvas px-3 py-2 text-sm">
                <div className="text-xs font-medium text-muted">Short interest{data.short.as_of ? ` · as of ${data.short.as_of}` : ''}</div>
                <div className="mt-1 flex flex-wrap gap-x-6 gap-y-1">
                  <span>{compact(data.short.shares)} shares short</span>
                  <span>{data.short.pct_of_float == null ? '—' : `${num(data.short.pct_of_float, 2)}%`} of float</span>
                  <span title="Days of average volume needed to buy back every short share">{num(data.short.days_to_cover, 1)} days to cover</span>
                  {data.short.change_pct != null && (
                    <span className={data.short.change_pct > 0 ? 'text-down' : 'text-up'}>{pct(data.short.change_pct, 1)} vs last month</span>
                  )}
                </div>
              </div>
            )}

            <Segmented size="sm" value={tab} onChange={(v) => setTab(v as Tab)} options={tabs} />
            {tab === 'insiders' &&
              (ins && ins.recent.length ? (
                <ul className="divide-y divide-line text-sm">
                  {ins.recent.map((r, i) => (
                    <li key={i} className="flex items-start justify-between gap-3 py-1.5">
                      <div className="min-w-0">
                        <div className="truncate">{r.insider} <span className="text-xs text-faint">· {r.position}</span></div>
                        <div className="truncate text-[12px] text-faint">{r.date} · {r.text || '—'}</div>
                      </div>
                      <div className="shrink-0 text-end">
                        <div className={cx('text-xs font-medium uppercase', r.side === 'buy' ? 'text-up' : r.side === 'sell' ? 'text-down' : 'text-muted')}>{r.side}</div>
                        <div className="tabular text-[12px] text-faint">{compact(r.shares)} sh{r.value ? ` · ${compact(r.value)}` : ''}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted">No insider trades reported in the last {ins?.days ?? 180} days.</p>
              ))}
            {tab === 'institutions' && <HolderTable rows={data.institutions} />}
            {tab === 'funds' && <HolderTable rows={data.funds} />}
            {tab === 'deals' && data.deals && <DealList deals={data.deals} showSymbol={false} />}
            <p className="text-[12px] text-faint">From exchange and regulatory filings; coverage outside the US is thinner.</p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function Mini({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return (
    <div className="rounded-lg bg-canvas px-3 py-2">
      <div className="text-[12px] text-faint">{label}</div>
      <div className={cx('tabular text-sm font-semibold', className)}>{value}</div>
      {sub && <div className="text-[11px] text-faint">{sub}</div>}
    </div>
  )
}

function HolderTable({ rows }: { rows: Holder[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-xs text-muted">
        <tr>
          <th className="py-1 text-start font-medium">Holder</th>
          <th className="py-1 text-end font-medium">% held</th>
          <th className="py-1 text-end font-medium">Change</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {rows.map((h) => (
          <tr key={h.holder} title={h.reported ? `Reported ${h.reported}` : undefined}>
            <td className="max-w-0 truncate py-1.5 pe-2">{h.holder}</td>
            <td className="tabular py-1.5 pe-2 text-end">{h.pct_held == null ? '—' : `${num(h.pct_held * 100, 2)}%`}</td>
            <td className={cx('tabular py-1.5 text-end', (h.pct_change ?? 0) >= 0 ? 'text-up' : 'text-down')}>
              {h.pct_change == null ? '—' : pct(h.pct_change * 100, 1)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** NSE bulk / block deals: named buyers and sellers of large blocks. */
export function DealList({ deals, showSymbol }: { deals: DealsResponse; showSymbol: boolean }) {
  const [all, setAll] = useState(false)
  if (!deals.deals.length) {
    return (
      <p className="text-sm text-muted">
        No bulk or block deals{deals.history_from ? ` since ${deals.history_from}` : ''}. History builds up from the day MarketMyna first collected it.
      </p>
    )
  }
  return (
    <div>
      <ul className="divide-y divide-line text-sm">
        {deals.deals.slice(0, all ? 150 : 15).map((d, i) => (
          <li key={i} className="flex items-start justify-between gap-3 py-1.5">
            <div className="min-w-0">
              <div className="truncate">
                {showSymbol && <span className="me-2 font-mono">{d.symbol}</span>}
                {d.client}
              </div>
              <div className="truncate text-[12px] text-faint">
                {d.date} · {d.kind} deal{d.remarks ? ` · ${d.remarks}` : ''}
              </div>
            </div>
            <div className="shrink-0 text-end">
              <div className={cx('text-xs font-medium uppercase', d.side === 'buy' ? 'text-up' : 'text-down')}>{d.side}</div>
              <div className="tabular text-[12px] text-faint">
                {compact(d.qty)} @ {num(d.price)}{d.value ? ` · ₹${compact(d.value)}` : ''}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {deals.deals.length > 15 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 text-xs text-accent-fg hover:underline">
          {all ? 'Show fewer' : `Show all ${deals.deals.length}`}
        </button>
      )}
      <p className="mt-2 text-[12px] text-faint">Bulk = over 0.5% of the company's shares in a day; block = a single large trade in the block window. Source: NSE.</p>
    </div>
  )
}
