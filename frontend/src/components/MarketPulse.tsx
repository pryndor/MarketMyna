import { useContext, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { analyzeLink, getDiscovery, type Discovery, type MoverRow } from '../api/listings'
import { cx } from '../lib/cx'
import { compact, num, pct, price, relativeTime, trendClass } from '../lib/format'
import { InsightActive, liveEvery, useFlash, useInsight } from '../lib/insight'
import { useLiveQuotes } from '../lib/liveQuotes'
import { ScrollBox, Segmented } from './ui'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'

type Board = 'gainers' | 'losers' | 'active' | 'near_high' | 'near_low'

const BOARDS = [
  { value: 'gainers', label: 'Gainers' },
  { value: 'losers', label: 'Losers' },
  { value: 'active', label: 'Most active' },
  { value: 'near_high', label: 'Near 52w high' },
  { value: 'near_low', label: 'Near 52w low' },
]

const SIZES = [
  { value: '100', label: 'Top 100' },
  { value: '500', label: 'Top 500' },
  { value: '2000', label: 'Top 2000' },
]


/** Market snapshot above the listings table: indices, breadth, leader boards, sectors. */
export default function MarketPulse({ market, onCategory }: { market: string; onCategory: (category: string) => void }) {
  const [size, setSize] = useState('500')
  const [board, setBoard] = useState<Board>('gainers')
  // Re-ranked on live prices by the server; refreshed in place while open.
  const { data, error, at } = useInsight((signal) => getDiscovery(market, Number(size), signal), [market, size], liveEvery(15_000))

  const sizeLabel = market === 'crypto' ? 'by volume' : 'by market cap'
  // The board is re-ranked every few seconds by the server; the prices on
  // screen tick every second from the same feed as the listings table.
  const active = useContext(InsightActive)
  const ranked = useMemo(() => (data ? data[board] : []).map((r) => ({ ...r, market })), [data, board, market])
  const ticking = useLiveQuotes(ranked, active)
  const rows = ticking.rows
  const flash = useFlash(
    Object.fromEntries([
      ...(data?.indices ?? []).map((i) => [`i:${i.name}`, i.price]),
    ]),
  )

  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Market pulse</h2>
          {data && (
            <p className="text-xs text-muted">
              Leaders among the {data.universe.toLocaleString()} largest {sizeLabel}
              {data.live?.live ? (data.live.open ? ' on live prices' : '') : data.as_of ? ` · prices ${relativeTime(data.as_of)}` : ''}
            </p>
          )}
          {data && <InsightLive live={data.live} at={at} ticking={ticking.status.updated} />}
        </div>
      </div>

      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Fetching index levels…', 'Counting advancing and declining stocks…', 'Ranking gainers and losers…', 'Weighing sectors by market cap…']} />}
        {data && (
          <>
            <div className="flex flex-wrap items-stretch gap-3">
              {data.indices.map((i) => (
                <div key={i.name} className="min-w-[140px] rounded-lg bg-canvas px-3 py-2">
                  <div className="text-xs text-muted">{i.name}</div>
                  <div className={cx('tabular rounded text-sm font-semibold', flash(`i:${i.name}`))}>{num(i.price)}</div>
                  <div className={cx('tabular text-xs', trendClass(i.change_percent))}>{pct(i.change_percent)}</div>
                </div>
              ))}
              <Breadth breadth={data.breadth} />
            </div>

            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="min-w-0 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Segmented size="sm" value={board} onChange={(v) => setBoard(v as Board)} options={BOARDS} />
                  <Segmented size="sm" value={size} onChange={setSize} options={SIZES} />
                </div>
                {rows.length > 0 && (
                  <div className="text-xs text-faint">
                    {rows.length} {rows.length === 1 ? 'stock' : 'stocks'} among the top {Number(size).toLocaleString()}
                    {rows.length > 10 ? ' · scroll for more' : ''}
                  </div>
                )}
                <MoverTable rows={rows} market={market} board={board} flash={ticking.flash} />
              </div>
              {data.sectors.length > 0 && <Sectors sectors={data.sectors} market={market} onCategory={onCategory} />}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Breadth({ breadth }: { breadth: Discovery['breadth'] }) {
  const { advancers, decliners, unchanged, total } = breadth
  if (!total) return null
  const w = (n: number) => `${(n / total) * 100}%`
  return (
    <div className="min-w-[220px] flex-1 rounded-lg bg-canvas px-3 py-2">
      <div className="flex justify-between text-xs text-muted">
        <span>Breadth · {total.toLocaleString()} stocks</span>
        <span className="tabular">
          <span className="text-up">{advancers.toLocaleString()} up</span> · <span className="text-down">{decliners.toLocaleString()} down</span>
        </span>
      </div>
      <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-raised" title={`${unchanged} unchanged`}>
        <div className="bg-up" style={{ width: w(advancers) }} />
        <div className="bg-line-strong" style={{ width: w(unchanged) }} />
        <div className="bg-down" style={{ width: w(decliners) }} />
      </div>
    </div>
  )
}

function MoverTable({ rows, market, board, flash }: { rows: MoverRow[]; market: string; board: Board; flash: (r: MoverRow & { market: string }) => string }) {
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted">
        {board.startsWith('near') ? 'No 52-week range data for this market, or nothing near it today.' : 'Nothing to show.'}
      </p>
    )
  }
  const showValue = board === 'active'
  const ref = board === 'near_high' ? 'high_52w' : board === 'near_low' ? 'low_52w' : null
  // Up to 50 rows: the list scrolls inside its own box so the section keeps its height.
  return (
    <ScrollBox className="pe-1">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td className="w-full max-w-0 py-1.5 pe-2">
                <Link to={analyzeLink({ symbol: r.symbol, market })} className="font-mono text-sm hover:text-accent-fg">
                  {r.symbol}
                </Link>
                <div className="truncate text-[12px] text-faint">{r.name}</div>
              </td>
              <td className={cx('tabular whitespace-nowrap py-1.5 pe-2 text-end', flash({ ...r, market }))}>{price(r.price, r.currency)}</td>
              <td className={cx('tabular py-1.5 pe-2 text-end', trendClass(r.change_percent))}>{pct(r.change_percent)}</td>
              <td className="tabular hidden whitespace-nowrap py-1.5 text-end text-xs text-muted sm:table-cell">
                {showValue
                  ? `${compact(r.traded_value)} traded`
                  : ref && r[ref] && r.price
                    ? `${pct((r.price / (r[ref] as number) - 1) * 100, 1)} vs ${board === 'near_high' ? 'high' : 'low'}`
                    : r.market_cap
                      ? `cap ${compact(r.market_cap)}`
                      : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollBox>
  )
}

function Sectors({ sectors, market, onCategory }: { sectors: Discovery['sectors']; market: string; onCategory: (c: string) => void }) {
  // A click pins a sector (and lists its biggest stocks) until clicked again.
  const [picked, setPicked] = useState<string | null>(null)
  useEffect(() => setPicked(null), [market])
  const max = Math.max(0.5, ...sectors.map((s) => Math.abs(s.change_percent ?? 0)))
  const sel = sectors.find((s) => s.sector === picked)
  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs font-medium text-muted">Sectors (cap-weighted day change) · click to pin</div>
      <ScrollBox className="pe-1">
        <ul className="space-y-1">
          {sectors.map((s) => {
            const v = s.change_percent ?? 0
            const selected = picked === s.sector
            return (
              <li key={s.sector}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setPicked(selected ? null : s.sector)}
                  className={cx(
                    'grid w-full grid-cols-[minmax(0,9rem)_minmax(0,1fr)_4rem] items-center gap-2 rounded px-1 py-0.5 text-start text-xs transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent',
                    selected ? 'bg-accent-soft font-medium shadow-[inset_3px_0_0_var(--color-accent)]' : 'hover:bg-raised',
                  )}
                  title={selected ? 'Click again to unpin' : `Click to pin · ${s.count} stocks · ${s.advancers} up / ${s.decliners} down${s.leader ? ` · best ${s.leader.symbol} ${pct(s.leader.change_percent, 1)}` : ''}${s.laggard ? ` · worst ${s.laggard.symbol} ${pct(s.laggard.change_percent, 1)}` : ''}`}
                >
                  <span className={cx('truncate', selected && 'ps-1.5')}>{s.sector}</span>
                  <span className="relative h-2 rounded-full bg-raised">
                    <span
                      className={cx('absolute top-0 h-2 rounded-full', v >= 0 ? 'left-1/2 bg-up' : 'right-1/2 bg-down')}
                      style={{ width: `${(Math.abs(v) / max) * 50}%` }}
                    />
                  </span>
                  <span className={cx('tabular text-end', trendClass(v))}>{pct(s.change_percent)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </ScrollBox>
      {sel && (
        <div className="mt-3 rounded-lg border border-accent/40 bg-accent-soft px-3 py-2.5">
          <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
            <span className="min-w-0 truncate font-medium text-fg">
              {sel.sector} · <span className={trendClass(sel.change_percent)}>{pct(sel.change_percent)}</span>
              <span className="font-normal text-muted"> · {sel.advancers} up / {sel.decliners} down of {sel.count}</span>
            </span>
            <span className="flex shrink-0 gap-3">
              <button type="button" onClick={() => onCategory(sel.sector)} className="text-accent-fg hover:text-fg">
                Filter list
              </button>
              <button type="button" onClick={() => setPicked(null)} className="text-muted hover:text-fg">
                Unpin
              </button>
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(sel.members ?? []).map((m) => (
              <Link
                key={m.symbol}
                to={analyzeLink({ symbol: m.symbol, market })}
                className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-xs hover:border-accent hover:text-accent-fg"
              >
                {m.symbol} <span className={cx('tabular', trendClass(m.change_percent))}>{pct(m.change_percent, 1)}</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
