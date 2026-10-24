import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getBigTrades, type BigTrade, type BigTrades, type WhalePosition } from '../api/listings'
import { cx } from '../lib/cx'
import { useEnglishNames } from '../lib/english'
import EnglishToggle from './EnglishToggle'
import { compact, num, pct, trendClass } from '../lib/format'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import { ScrollBox, Segmented } from './ui'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'

const RANGES = [
  { value: '1', label: 'Latest day' },
  { value: '7', label: '7 days' },
]

const STEPS: Record<string, string[]> = {
  us: ['Reading the latest insider filings (Form 4)…', 'Keeping open-market buys and sells…', 'Sorting by dollar value…'],
  china_a: ['Fetching Shanghai and Shenzhen block trades…', 'Sorting by deal size…'],
  hong_kong: ['Fetching southbound Stock Connect flows…', 'Sorting by net amount…'],
  crypto: ['Reading big-trader positioning from crypto futures…', 'Comparing open interest over the week…'],
}

const SIDE_CLASS = (side: string) =>
  side.includes('buy') || side === 'premium' ? 'text-up' : side.includes('sell') || side === 'discount' ? 'text-down' : 'text-muted'

function TradeList({ data }: { data: BigTrades }) {
  const [all, setAll] = useState(false)
  const deals = data.deals ?? []
  const shown = deals.slice(0, all ? 200 : 20)
  const english = useEnglishNames(data.market, shown, shown.map((d) => d.client))
  if (!deals.length) return <p className="text-sm text-muted">No trades in this window.</p>
  return (
    <div>
      <ul className="divide-y divide-line text-sm">
        {shown.map((d: BigTrade, i) => (
          <li key={i} className="flex items-start justify-between gap-3 py-1.5">
            <div className="min-w-0">
              <div className="truncate">
                <Link to={`/analyze?symbol=${encodeURIComponent(d.symbol)}&market=${data.market}`} className="me-2 font-mono hover:text-accent-fg">
                  {d.symbol}
                </Link>
                <span className="text-muted" title={d.name_local ?? d.name ?? undefined}>{english.name(d.symbol, d.name)}</span>
              </div>
              <div className="truncate text-[12px] text-faint" title={d.client ?? undefined}>
                {d.date} · {english.text(d.client)}
                {d.remarks ? ` · ${d.remarks}` : ''}
              </div>
            </div>
            <div className="shrink-0 text-end">
              <div className={cx('text-xs font-medium uppercase', SIDE_CLASS(d.side))}>{d.side}</div>
              <div className="tabular text-[12px] text-faint">
                {d.qty != null && d.price != null ? `${compact(d.qty)} @ ${num(d.price)} · ` : ''}
                {d.value != null ? `${data.currency}${compact(d.value)}` : ''}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {deals.length > 20 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 text-xs text-accent-fg hover:underline">
          {all ? 'Show fewer' : `Show all ${deals.length}`}
        </button>
      )}
    </div>
  )
}

function Positions({ rows }: { rows: WhalePosition[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full min-w-[36rem] text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="py-2 text-start font-medium">Coin</th>
            <th className="px-2 py-2 text-start font-medium">Top traders long</th>
            <th className="px-2 py-2 text-end font-medium">L/S ratio</th>
            <th className="px-2 py-2 text-end font-medium">Open interest</th>
            <th className="px-2 py-2 text-end font-medium">OI 1d</th>
            <th className="px-2 py-2 text-end font-medium">OI 7d</th>
            <th className="px-2 py-2 text-end font-medium">Taker buy/sell</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.coin}>
              <td className="py-2">
                <Link to={`/analyze?symbol=${r.coin}-USD&market=crypto`} className="font-mono text-xs font-medium hover:text-accent-fg">
                  {r.coin}
                </Link>
              </td>
              <td className="px-2 py-2">
                <div className="flex items-center gap-2">
                  <div className="flex h-1.5 w-24 overflow-hidden rounded-full bg-down/60">
                    <div className="bg-up" style={{ width: `${r.top_long_pct}%` }} />
                  </div>
                  <span className="text-xs">{num(r.top_long_pct, 0)}%</span>
                </div>
              </td>
              <td className="px-2 py-2 text-end">
                {num(r.top_ratio, 2)}
                <span className={cx('ms-1 text-[12px]', trendClass(r.top_ratio_change))}>
                  {r.top_ratio_change > 0 ? '▲' : r.top_ratio_change < 0 ? '▼' : ''}
                </span>
              </td>
              <td className="px-2 py-2 text-end">${compact(r.open_interest)}</td>
              <td className={cx('px-2 py-2 text-end', trendClass(r.oi_change_1d))}>{pct(r.oi_change_1d, 1)}</td>
              <td className={cx('px-2 py-2 text-end', trendClass(r.oi_change_7d))}>{pct(r.oi_change_7d, 1)}</td>
              <td className={cx('px-2 py-2 text-end', r.taker_ratio == null ? '' : r.taker_ratio >= 1 ? 'text-up' : 'text-down')}>
                {num(r.taker_ratio, 2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Big trades outside India: US insider trades, China block trades, HK
 * southbound flows, crypto big-trader positioning (India: DealsCard). */
export default function BigTradesCard({ market }: { market: string }) {
  const [days, setDays] = useState('1')
  const ranged = market === 'china_a' || market === 'hong_kong'
  // Filings and exchange reports arrive through the day: check for new ones.
  const { data, error, at } = useInsight<BigTrades>(
    (signal) => getBigTrades(market, ranged ? Number(days) : 1, signal),
    [market, days, ranged],
    DAILY_EVERY,
  )

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{data?.title ?? 'Big trades'}</h2>
          <p className="text-xs text-muted">{data?.subtitle ?? 'Large trades and positioning by big investors'}</p>
          <InsightLive at={at} daily="Checked for new trades every 10 min" />
        </div>
        <div className="flex items-center gap-2">
          {market === 'china_a' && <EnglishToggle />}
          {ranged && <Segmented size="sm" value={days} onChange={setDays} options={RANGES} />}
        </div>
      </div>
      <div className="space-y-2 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={STEPS[market] ?? ['Loading…']} />}
        {data && (
          <>
            <ScrollBox>{data.positions ? <Positions rows={data.positions} /> : <TradeList data={data} />}</ScrollBox>
            <p className="text-[12px] text-faint">{data.note}</p>
          </>
        )}
      </div>
    </div>
  )
}
