import { useEffect, useState } from 'react'
import { getCommodities, getCot, getEia, type Commodity, type CotItem, type EiaItem } from '../api/macro'
import { cx } from '../lib/cx'
import { num, pct, trendClass } from '../lib/format'
import { liveEvery, useFlash, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'
import MiniSparkline from './MiniSparkline'

const GROUPS: Array<{ key: Commodity['group']; label: string }> = [
  { key: 'india', label: 'In rupees' },
  { key: 'metals', label: 'Metals' },
  { key: 'energy', label: 'Energy' },
  { key: 'agri', label: 'Grains' },
]

function price(c: Commodity): string {
  if (c.unit.startsWith('₹')) return c.price.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
  return num(c.price, c.price < 20 ? 3 : 2)
}

/** Gold, silver, oil, gas, copper and grains futures; gold / silver also in rupees. */
export default function CommoditiesCard({ market }: { market: string }) {
  // Each contract's latest price is patched in by the server every minute.
  const { data, error, at } = useInsight((signal) => getCommodities(signal), [], liveEvery(60_000))
  const items = data?.items ?? null
  const flash = useFlash(Object.fromEntries((items ?? []).map((c) => [c.key, c.price])))
  const [cot, setCot] = useState<{ items: CotItem[]; as_of: string | null; source: string } | null>(null)
  const [eia, setEia] = useState<{ items: EiaItem[]; week_ending: string | null; source: string } | null>(null)


  // Positioning loads after prices, so a slow CFTC answer never holds up the tiles.
  useEffect(() => {
    if (!items || cot) return
    const controller = new AbortController()
    getCot(controller.signal)
      .then(setCot)
      .catch(() => !controller.signal.aborted && setCot({ items: [], as_of: null, source: '' }))
    return () => controller.abort()
  }, [items, cot])

  useEffect(() => {
    if (!items || eia) return
    const controller = new AbortController()
    getEia(controller.signal)
      .then(setEia)
      .catch(() => !controller.signal.aborted && setEia({ items: [], week_ending: null, source: '' }))
    return () => controller.abort()
  }, [items, eia])

  const groups = market === 'india' ? GROUPS : [...GROUPS.slice(1), GROUPS[0]]

  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Commodities</h2>
          <p className="text-xs text-muted">Gold, silver, oil, gas, copper and grains (front-month futures)</p>
          {data && <InsightLive live={data.live} at={at} />}
        </div>
      </div>
      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!items && !error && <InsightLoader className="min-h-56" steps={['Fetching metal prices…', 'Fetching energy prices…', 'Converting to rupees…']} />}
        {items && items.length === 0 && <p className="text-sm text-muted">Commodity prices are unavailable right now.</p>}
        {items &&
          groups.map((g) => {
            const rows = items.filter((c) => c.group === g.key)
            if (!rows.length) return null
            return (
              <div key={g.key}>
                <div className="mb-2 text-xs font-medium text-muted">{g.label}</div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {rows.map((c) => <Tile key={c.key} c={c} flash={flash(c.key)} />)}
                </div>
              </div>
            )
          })}
        {items && items.length > 0 && (
          <p className="text-[12px] text-faint">
            Source: futures prices from our market data feed, delayed. Rupee prices are international prices converted at the day's USD/INR,
            before import duty and GST, so MCX and jeweller prices run higher.
          </p>
        )}
        {items && items.length > 0 && <Positioning cot={cot} />}
        {items && items.length > 0 && <Inventories eia={eia} />}
      </div>
    </div>
  )
}

function Tile({ c, flash }: { c: Commodity; flash: string }) {
  const up = c.spark.length < 2 || c.spark[c.spark.length - 1] >= c.spark[0]
  return (
    <div className={cx('rounded-lg bg-canvas px-3 py-2', flash)} title={c.note}>
      <div className="flex justify-between gap-2 text-xs text-muted">
        <span className="truncate">{c.label}</span>
        <span className="shrink-0 text-faint">{c.unit}</span>
      </div>
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="tabular text-lg font-semibold">{price(c)}</div>
          <div className="tabular whitespace-nowrap text-[11px] text-faint">
            1d <span className={trendClass(c.change_1d)}>{pct(c.change_1d, 1)}</span> · 1y{' '}
            <span className={trendClass(c.change_1y)}>{pct(c.change_1y, 1)}</span>
          </div>
        </div>
        <MiniSparkline values={c.spark} up={up} />
      </div>
    </div>
  )
}

function contracts(n: number): string {
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return sign + Math.abs(n).toLocaleString('en-US')
}

/** CFTC Commitments of Traders: hedge-fund net position and its place in a 3-year range. */
function Positioning({ cot }: { cot: { items: CotItem[]; as_of: string | null; source: string } | null }) {
  if (!cot) return <p className="text-xs text-muted">Loading fund positioning…</p>
  if (!cot.items.length) return <p className="text-xs text-muted">Fund positioning (CFTC) is unavailable right now.</p>
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
        <span className="font-medium text-muted">Fund positioning (CFTC)</span>
        <span className="text-faint">Positions as of {cot.as_of}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cot.items.map((c) => (
          <div key={c.key} className="rounded-lg bg-canvas px-3 py-2">
            <div className="flex justify-between gap-2 text-xs text-muted">
              <span className="truncate">{c.label}</span>
              <span className="shrink-0 text-faint">{c.net_pct_oi != null ? `${c.net_pct_oi}% of OI` : ''}</span>
            </div>
            <div className="tabular text-sm font-semibold" title="Managed money (hedge funds, CTAs) long minus short, in contracts">
              {contracts(c.managed_money_net)} <span className="text-[11px] font-normal text-faint">net contracts</span>
            </div>
            <div className="tabular text-[11px] text-faint">
              1w <span className={trendClass(c.net_change_1w)}>{c.net_change_1w != null ? contracts(c.net_change_1w) : '—'}</span>
              {' · '}producers {contracts(c.producer_net)}
            </div>
            {c.index_3y != null && (
              <div className="mt-1.5" title={`3-year position index ${c.index_3y} (0 = most short, 100 = most long in 3 years)`}>
                <div className="relative h-1.5 rounded-full bg-line">
                  <div className="absolute top-1/2 h-3 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-fg" style={{ left: `${c.index_3y}%` }} />
                </div>
                <div className="mt-1 text-[11px] text-muted">{c.reading} ({c.index_3y}/100)</div>
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="mt-2 text-[12px] text-faint">
        Source: {cot.source}. Shows how positions stand, not where prices will go. Brent is not covered (it trades on ICE Europe).
      </p>
    </div>
  )
}

function signed(n: number, digits: number): string {
  return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(digits)
}

/** EIA weekly US oil stocks against the 5-year average for the same week. */
function Inventories({ eia }: { eia: { items: EiaItem[]; week_ending: string | null; source: string } | null }) {
  if (!eia) return <p className="text-xs text-muted">Loading US oil inventories…</p>
  if (!eia.items.length) return <p className="text-xs text-muted">US oil inventories (EIA) are unavailable right now.</p>
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
        <span className="font-medium text-muted">US oil inventories (EIA)</span>
        <span className="text-faint">Week ending {eia.week_ending}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {eia.items.map((c) => {
          const pctUnit = c.unit === '%'
          return (
            <div key={c.key} className="rounded-lg bg-canvas px-3 py-2" title={c.note}>
              <div className="flex justify-between gap-2 text-xs text-muted">
                <span className="truncate">{c.label}</span>
                <span className="shrink-0 text-faint">{pctUnit ? '% of capacity' : 'million bbl'}</span>
              </div>
              <div className="tabular text-lg font-semibold">{c.value.toFixed(1)}{pctUnit ? '%' : ''}</div>
              <div className="tabular text-[11px] text-faint">
                1w {signed(c.change_1w, pctUnit ? 1 : 2)}{pctUnit ? ' pts' : ''}
                {c.vs_avg_5y != null && (
                  <>
                    {' · '}vs 5-yr avg {signed(c.vs_avg_5y, 1)}{pctUnit ? ' pts' : '%'}
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <p className="mt-2 text-[12px] text-faint">
        Source: {eia.source}. The 5-year average is for the same week of the year, since stocks rise and fall with the seasons.
      </p>
    </div>
  )
}
