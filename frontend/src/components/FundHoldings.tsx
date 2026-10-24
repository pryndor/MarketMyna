import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getFundHoldings, type FundHolding, type FundHoldings as Data } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { Skeleton } from './ui'

const KINDS: Record<FundHolding['kind'], { label: string; color: string }> = {
  equity: { label: 'Indian stocks', color: '#6d8cff' },
  foreign_equity: { label: 'Foreign stocks', color: '#22d3ee' },
  reit: { label: 'REITs / InvITs', color: '#a78bfa' },
  debt: { label: 'Bonds & money market', color: '#fbbf24' },
  fund: { label: 'Other funds', color: '#f472b6' },
  cash: { label: 'Cash & other', color: '#94a3b8' },
}
const SHOW = 10

function Bar({ label, weight, scale, href, sub }: { label: string; weight: number; scale: number; href?: string; sub?: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_5rem_3.25rem] items-center gap-2 py-1 text-sm">
      <span className="min-w-0 truncate" title={sub ? `${label} · ${sub}` : label}>
        {href ? (
          <Link to={href} className="hover:text-accent-fg">
            {label}
          </Link>
        ) : (
          label
        )}
      </span>
      <span className="h-2 rounded-full bg-raised">
        <span className="block h-2 rounded-full bg-accent" style={{ width: `${Math.min((weight / scale) * 100, 100)}%` }} />
      </span>
      <span className="tabular text-end text-xs">{num(weight, 2)}%</span>
    </div>
  )
}

const stockHref = (symbol: string | null) => (symbol ? `/analyze?symbol=${encodeURIComponent(symbol)}&market=india` : undefined)

/** What a mutual fund holds, from its fund house's official monthly portfolio. */
const CAPS: Record<string, { label: string; color: string; hint: string }> = {
  large: { label: 'Large cap', color: 'var(--color-accent)', hint: 'The 100 largest listed companies (SEBI)' },
  mid: { label: 'Mid cap', color: 'var(--color-up)', hint: 'Companies ranked 101-250 by market cap' },
  small: { label: 'Small cap', color: 'var(--color-warn)', hint: 'Companies ranked 251 and below' },
  foreign: { label: 'Foreign', color: 'var(--color-faint)', hint: 'Shares listed outside India' },
  other: { label: 'Unlisted / other', color: 'var(--color-line-strong)', hint: 'Not matched to a listed Indian company' },
}

export default function FundHoldings({ code }: { code: string }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [all, setAll] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError(null)
    setAll(false)
    getFundHoldings(code, controller.signal)
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [code])

  if (error) return <p className="text-xs text-muted">Holdings unavailable: {error}</p>
  if (!data) return <Skeleton className="h-48 w-full" />
  if (data.status !== 'ok') {
    return (
      <div className="rounded-lg border border-dashed border-line-strong p-4 text-sm">
        <div className="font-medium">Stock list not loaded for this fund house yet</div>
        <p className="mt-1 text-xs text-muted">
          {data.note} Each fund house publishes every scheme's full portfolio once a month; once {data.amc ?? 'its'} file
          is loaded, the stocks, sectors and company sizes show up here. The competitor comparison below works for every fund.
        </p>
      </div>
    )
  }

  const stocks = (data.holdings ?? []).filter((h) => h.kind === 'equity' || h.kind === 'foreign_equity')
  const others = (data.holdings ?? []).filter((h) => h.kind !== 'equity' && h.kind !== 'foreign_equity')
  const list = all ? stocks : stocks.slice(0, SHOW)
  const scale = Math.max(...stocks.map((h) => h.weight), 1)
  const sectors = (data.sectors ?? []).slice(0, 8)
  const sectorScale = Math.max(...sectors.map((s) => s.weight), 1)
  const ch = data.changes
  const asOf = data.as_of ? new Date(data.as_of).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : null

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">What it holds</h3>
          <span className="text-xs text-faint">
            {data.weights === 'estimated' ? 'Estimated from the NSE index list' : `${data.source}${asOf ? ` · ${asOf}` : ''}`}
          </span>
        </div>
        {data.note && <p className="mt-1 text-xs text-muted">{data.note}</p>}
      </div>

      {data.mix && data.mix.length > 0 && (
        <div>
          <div className="flex h-3 overflow-hidden rounded-full bg-raised">
            {data.mix.map((m) => (
              <span key={m.kind} style={{ width: `${Math.max(m.weight, 0)}%`, background: KINDS[m.kind]?.color }} title={`${KINDS[m.kind]?.label}: ${num(m.weight, 1)}%`} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            {data.mix.map((m) => (
              <span key={m.kind} className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: KINDS[m.kind]?.color }} />
                {KINDS[m.kind]?.label} <span className="tabular text-fg">{num(m.weight, 1)}%</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 rounded-lg bg-canvas p-4 sm:grid-cols-5">
        <div>
          <div className="text-xs text-faint">Stocks</div>
          <div className="tabular text-sm font-semibold">{data.count}</div>
        </div>
        {data.concentration?.effective_stocks != null && (
          <div title="1 ÷ the sum of squared weights: how many equal-sized positions the fund behaves like">
            <div className="text-xs text-faint">Behaves like</div>
            <div className="tabular text-sm font-semibold">{num(data.concentration.effective_stocks, 0)} stocks</div>
          </div>
        )}
        {data.churn && (
          <div title={`Last month: bought ₹${num(data.churn.bought_cr, 0)} Cr, sold ₹${num(data.churn.sold_cr, 0)} Cr of shares. Turnover = the smaller of the two over fund size (SEBI's definition), ×12 for a year.`}>
            <div className="text-xs text-faint">Turnover, yearly rate</div>
            <div className="tabular text-sm font-semibold">{num(data.churn.yearly_pct, 0)}%</div>
          </div>
        )}
        <div>
          <div className="text-xs text-faint">Top 10 weight</div>
          <div className="tabular text-sm font-semibold">{num(data.top10_weight ?? 0, 1)}%</div>
        </div>
        <div>
          <div className="text-xs text-faint">Fund size</div>
          <div className="tabular text-sm font-semibold">{data.aum_cr ? `₹${num(data.aum_cr, 0)} Cr` : '—'}</div>
        </div>
      </div>

      {(data.concentration?.effective_stocks != null || data.churn) && (
        <p className="text-xs text-muted">
          {data.concentration?.effective_stocks != null &&
            `It holds ${data.count} stocks but behaves like ${num(data.concentration.effective_stocks, 0)} equal-sized positions${data.concentration.effective_stocks < 20 ? ' (concentrated: a few names drive it)' : data.concentration.effective_stocks > 50 ? ' (widely spread)' : ''}. `}
          {data.churn &&
            `Last month's trading implies about ${num(data.churn.yearly_pct, 0)}% turnover a year: ${data.churn.yearly_pct < 20 ? 'low, it mostly holds' : data.churn.yearly_pct < 60 ? 'moderate' : 'high, it trades a lot (more costs, more short-term bets)'}. One month is a rough guide.`}
        </p>
      )}

      {data.cap_split && data.cap_split.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium text-muted">Company size (share of the fund)</div>
          <div className="flex h-3 overflow-hidden rounded-full bg-raised">
            {data.cap_split.map((c) => (
              <span key={c.kind} style={{ width: `${Math.max(c.weight, 0)}%`, background: CAPS[c.kind].color }} title={`${CAPS[c.kind].label}: ${num(c.weight, 1)}%`} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            {data.cap_split.map((c) => (
              <span key={c.kind} className="inline-flex items-center gap-1.5" title={CAPS[c.kind].hint}>
                <span className="h-2 w-2 rounded-full" style={{ background: CAPS[c.kind].color }} />
                {CAPS[c.kind].label} <span className="tabular text-fg">{num(c.weight, 1)}%</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {stocks.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted">Stocks by weight</div>
          {list.map((h) => (
            <Bar
              key={`${h.isin ?? h.name}-${h.kind}`}
              label={h.name}
              weight={h.weight}
              scale={scale}
              href={h.kind === 'equity' ? stockHref(h.symbol) : undefined}
              sub={[h.kind === 'foreign_equity' ? 'Foreign' : null, h.sector, h.hedged ? `${num(h.hedged, 2)}% hedged (arbitrage)` : null].filter(Boolean).join(' · ')}
            />
          ))}
          {stocks.length > SHOW && (
            <button type="button" onClick={() => setAll((v) => !v)} className="mt-1 text-xs text-accent-fg hover:underline">
              {all ? 'Show top 10' : `Show all ${stocks.length} stocks`}
            </button>
          )}
        </div>
      )}

      {sectors.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted">Sectors</div>
          {sectors.map((s) => (
            <Bar key={s.name} label={s.name} weight={s.weight} scale={sectorScale} />
          ))}
        </div>
      )}

      {ch && (ch.new.length > 0 || ch.exited.length > 0 || ch.moved.length > 0) && (
        <div>
          <div className="mb-2 text-xs font-medium text-muted">
            Changes since {ch.since ? new Date(ch.since).toLocaleDateString(undefined, { month: 'short', year: 'numeric' }) : 'last month'}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <ChangeList title="New buys" tone="text-up" items={ch.new.map((c) => ({ name: c.name, symbol: c.symbol, text: `${num(c.weight, 2)}%` }))} />
            <ChangeList title="Sold out" tone="text-down" items={ch.exited.map((c) => ({ name: c.name, symbol: null, text: `was ${num(c.weight, 2)}%` }))} />
            <ChangeList
              title="Biggest changes"
              tone="text-fg"
              items={ch.moved.map((c) => ({
                name: c.name,
                symbol: c.symbol,
                text: `${num(c.from, 1)} → ${num(c.to, 1)}%`,
                up: c.to > c.from,
              }))}
            />
          </div>
        </div>
      )}

      {others.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-medium text-muted">Bonds, REITs and other holdings ({others.length})</summary>
          <div className="mt-2">
            {others.slice(0, 40).map((h) => (
              <Bar key={`${h.isin}-${h.kind}`} label={h.name} weight={h.weight} scale={scale} sub={`${KINDS[h.kind]?.label}${h.sector ? ` · ${h.sector}` : ''}`} />
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

function ChangeList({ title, tone, items }: { title: string; tone: string; items: { name: string; symbol: string | null; text: string; up?: boolean }[] }) {
  return (
    <div className="min-w-0">
      <div className={cx('text-xs font-semibold', tone)}>{title}</div>
      {items.length === 0 ? (
        <div className="mt-1 text-xs text-faint">None</div>
      ) : (
        <ul className="mt-1 space-y-0.5 text-xs">
          {items.slice(0, 6).map((c) => (
            <li key={c.name} className="flex justify-between gap-2">
              <span className="min-w-0 truncate" title={c.name}>
                {c.symbol ? (
                  <Link to={stockHref(c.symbol)!} className="hover:text-accent-fg">
                    {c.name}
                  </Link>
                ) : (
                  c.name
                )}
              </span>
              <span className={cx('tabular shrink-0', c.up === undefined ? 'text-muted' : c.up ? 'text-up' : 'text-down')}>{c.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
