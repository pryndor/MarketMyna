import { useContext, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { compareLink } from '../api/compare'
import { listScreens, runCustomScreen, runScreen, type CustomScreen, type ScreenAsset, type ScreenPreset, type ScreenResult } from '../api/screens'
import { cx } from '../lib/cx'
import { useEnglishNames } from '../lib/english'
import EnglishToggle from './EnglishToggle'
import { compact, num, pct, price, trendClass } from '../lib/format'
import { InsightActive, useInsight } from '../lib/insight'
import { useLiveQuotes } from '../lib/liveQuotes'
import InsightLive from './InsightLive'
import ExportMenu from './ExportMenu'
import ScreenBuilder, { loadScreen } from './ScreenBuilder'
import { Icon, ScrollBox, Segmented, Spinner } from './ui'
import InsightLoader from './InsightLoader'


/** One screen cell: text for the sector, "2.7×" for sector-relative ratios. */
function cell(key: string, v: unknown): string {
  if (key === 'sector') return (v as string) || '—'
  const n = v as number | null
  if (key === 'pe_vs_sector' || key === 'pb_vs_sector') return n == null ? '—' : `${num(n, 1)}×`
  if (key === 'volume') return compact(n)
  if (key === 'analysts') return num(n, 0)
  return num(n, key === 'debt_equity' || key === 'pb' ? 2 : 1)
}

type Row = ScreenResult['results'][number]
const NO_ROWS: Row[] = []
// Ratios with price on top (or below) move with it between fundamentals updates.
const WITH_PRICE = ['pe', 'pb', 'ps', 'pe_vs_sector', 'pb_vs_sector', 'peg', 'market_cap']
const AGAINST_PRICE = ['dividend_yield', 'earnings_yield', 'fcf_yield']
const SCREEN_LIVE = { open: true, live: true, updated: null, age_seconds: null, refresh_seconds: 1, covered: 0, source: 'Live prices', error: null }

/** A screen row at the live price: P/E, P/B, PEG and market cap scale with
 * price, yields inversely, distance from the 52-week high / low follows. */
function live(r: Row, before: number | null | undefined): Row {
  const k = before && r.price ? r.price / before : 1
  if (k === 1) return r
  const out: Row = { ...r }
  for (const key of WITH_PRICE) if (typeof r[key] === 'number') out[key] = (r[key] as number) * k
  for (const key of AGAINST_PRICE) if (typeof r[key] === 'number') out[key] = (r[key] as number) / k
  for (const key of ['from_high', 'from_low']) if (typeof r[key] === 'number') out[key] = ((1 + (r[key] as number) / 100) * k - 1) * 100
  if (typeof r.target_upside === 'number') out.target_upside = ((1 + r.target_upside / 100) / k - 1) * 100
  return out
}

const DEFAULT_PRESET = (market: string, asset: ScreenAsset) =>
  market === 'crypto' ? 'volume_leaders' : asset === 'etf' ? 'most_traded' : 'undervalued_large'
const CUSTOM = 'custom'
// Markets whose ETFs have their own price-based screens (src/services/etf_screens.py).
const ETF_MARKETS = ['india', 'us', 'hong_kong', 'china_a']
const ASSETS = [
  { value: 'stock', label: 'Stocks' },
  { value: 'etf', label: 'ETFs' },
]

/** Ready-made screens: fundamentals over a market's largest stocks, or price
 * and volume over its most-traded ETFs, or over the most-traded coins for crypto. */
export default function ScreensCard({ market }: { market: string }) {
  const crypto = market === 'crypto'
  const [asset, setAsset] = useState<ScreenAsset>('stock')
  const etf = asset === 'etf' && ETF_MARKETS.includes(market)
  const kind: ScreenAsset = etf ? 'etf' : 'stock'
  // Coins and ETFs have no fundamentals: price and volume columns, no market cap, no custom builder.
  const priceBased = crypto || etf
  const [presets, setPresets] = useState<ScreenPreset[]>([])
  const [active, setActive] = useState(() => DEFAULT_PRESET(market, kind))
  const [presetsFor, setPresetsFor] = useState(`${market}:${kind}`)
  const [sectors, setSectors] = useState<string[]>([])
  if (presetsFor !== `${market}:${kind}`) {
    setPresetsFor(`${market}:${kind}`)
    setPresets([])
    setActive(DEFAULT_PRESET(market, kind))
    setSectors([])
  }
  const [custom, setCustom] = useState<CustomScreen>(loadScreen)
  const [runs, setRuns] = useState(0)
  const customKey = `${JSON.stringify(custom)}#${runs}`
  // Membership is re-checked every 5 minutes; prices tick every second and
  // the price-based ratios follow them (see live()).
  const { data, error, at } = useInsight<ScreenResult>(
    () =>
      active === CUSTOM
        ? runCustomScreen(custom, market).then((d) => {
            setSectors(d.sectors)
            return d
          })
        : runScreen(active, market, kind),
    [active, market, kind, active === CUSTOM ? customKey : ''],
    5 * 60_000,
  )
  const loading = !data && !error
  const onScreen = useContext(InsightActive)
  const ticking = useLiveQuotes(data?.results ?? NO_ROWS, onScreen)
  const results = useMemo(() => {
    const before = new Map((data?.results ?? []).map((r) => [r.symbol, r.price]))
    return ticking.rows.map((r) => live(r, before.get(r.symbol)))
  }, [ticking.rows, data])


  useEffect(() => {
    if (!presets.length) listScreens(market, kind).then(setPresets).catch(() => undefined)
  }, [presets.length, market, kind])


  const english = useEnglishNames(market, data?.results ?? [])
  const activeTitle = active === CUSTOM ? 'your screen' : presets.find((p) => p.key === active)?.title ?? 'this screen'
  const top5 = results.slice(0, 5).map((r) => ({ symbol: r.symbol, market }))

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Ready-made screens</h2>
          <p className="text-xs text-muted">
            {crypto
              ? 'Momentum, strength vs Bitcoin, oversold and breakout picks from the most-traded coins'
              : etf
                ? "Liquidity, returns, strength vs the index and volatility picks from the market's main ETFs"
                : "Value, growth, dividend and quality picks from the market's largest companies"}
          </p>
          {data && (
            <InsightLive
              live={ticking.status.updated != null ? { ...SCREEN_LIVE, open: Object.values(ticking.status.markets).some((m) => m.open) } : null}
              at={at}
              ticking={ticking.status.updated}
              daily="Re-checked every 5 min"
            />
          )}
        </div>
        {ETF_MARKETS.includes(market) && <Segmented options={ASSETS} value={kind} onChange={(v) => setAsset(v as ScreenAsset)} size="sm" />}
      </div>
      <div className="space-y-4 px-5 pb-4">
        <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 sm:mx-0 sm:flex-wrap sm:px-0">
          {(presets.length ? presets : [{ key: DEFAULT_PRESET(market, kind), title: priceBased ? 'Most traded' : 'Low-multiple large caps' } as ScreenPreset]).map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => setActive(p.key)}
              title={p.description}
              className={cx(
                'shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs',
                active === p.key ? 'border-accent bg-accent/10 text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg',
              )}
            >
              {loading && active === p.key && <Spinner className="me-1.5 inline-block h-3 w-3 align-[-2px] text-accent" />}
              {p.title}
            </button>
          ))}
          {!priceBased && (
            <button
              type="button"
              onClick={() => setActive(CUSTOM)}
              title="Pick your own metrics, values, sectors and columns"
              className={cx(
                'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-3 py-1 text-xs',
                active === CUSTOM ? 'border-accent bg-accent/10 text-fg' : 'border-dashed border-line text-muted hover:border-line-strong hover:text-fg',
              )}
            >
              {loading && active === CUSTOM ? <Spinner className="h-3 w-3 text-accent" /> : <Icon name="filter" className="h-3 w-3" />}
              Build your own
            </button>
          )}
        </div>

        {active === CUSTOM && <ScreenBuilder key={market} spec={custom} sectors={sectors} running={loading} onRun={(spec) => {
              setCustom(spec)
              setRuns((n) => n + 1)
            }} />}

        {error && <p className="text-sm text-down">{error}</p>}
        {(loading || !data) && !error && (
          <div className="space-y-2">
            <InsightLoader
              key={active}
              className="min-h-56"
              steps={[
                crypto ? 'Loading six months of coin prices…' : etf ? 'Loading a year of ETF prices…' : 'Loading the largest companies…',
                `Applying the rules for ${activeTitle.toLowerCase()}…`,
                'Collecting the matches…',
              ]}
            />
            {!data && (
              <p className="text-xs text-faint">
                {crypto
                  ? 'First run checks the 100 most-traded coins.'
                  : etf
                    ? 'First run checks about 120 of the main and most-traded ETFs.'
                    : 'First run checks the 200 largest companies; this can take half a minute.'}
              </p>
            )}
          </div>
        )}
        {data && !loading && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted">
                <span className="font-medium text-fg">{data.description}.</span> {data.rules.join(' · ')}
              </p>
              <div className="flex items-center gap-2">
              {market === 'china_a' && <EnglishToggle loading={english.loading} />}
              <ExportMenu
                title={`Screen ${data.title} ${market}`}
                subtitle={data.rules.join(' | ')}
                tables={() => [{
                  title: data.title,
                  columns: [
                    { key: 'symbol', label: 'Symbol' }, { key: 'name', label: 'Name' }, { key: 'sector', label: 'Sector' },
                    crypto
                      ? { key: 'volume', label: '24h volume', kind: 'money' as const }
                      : etf
                        ? { key: 'volume', label: 'Avg daily turnover', kind: 'money' as const }
                        : { key: 'market_cap', label: 'Market cap', kind: 'money' as const },
                    { key: 'price', label: 'Price', kind: 'number' },
                    ...data.columns.map((c) => ({ key: c.key, label: c.label, kind: c.key === 'sector' ? undefined : ('number' as const) })),
                  ],
                  rows: results,
                  note: `${data.description}. Rules: ${data.rules.join('; ')}. ${data.universe}. ${crypto ? 'Prices from crypto exchange data.' : etf ? 'Daily prices from the market data feed.' : 'Fundamentals from the market data feed.'}`,
                }]}
              />
              {top5.length >= 2 && (
                <Link to={compareLink(top5)} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg">
                  <Icon name="compare" className="h-3.5 w-3.5" /> Compare top {top5.length}
                </Link>
              )}
              </div>
            </div>
            {active === 'expensive_sector' && (
              <details className="rounded-lg bg-canvas px-3 py-2 text-xs text-muted">
                <summary className="cursor-pointer font-medium text-fg">How to read this</summary>
                <ul className="mt-2 list-disc space-y-1 ps-4">
                  <li>
                    <b className="text-fg">P/E</b>: share price ÷ yearly profit per share. A P/E of 120 means you pay ₹120 for
                    every ₹1 the company earns in a year.
                  </li>
                  <li>
                    <b className="text-fg">Sector P/E</b>: the middle P/E among the largest companies in the same sector, since
                    each industry normally trades at its own level. <b className="text-fg">P/E × sector</b> = how many times
                    that level this stock costs. Listed when above 1.5×.
                  </li>
                  <li>
                    <b className="text-fg">PEG</b>: P/E ÷ profit growth %. Around 1 means price and growth match; above 2 the
                    price runs well ahead of growth. Listed only when PEG is above 2 or profits are shrinking, so fast growers
                    that earn their price are left out.
                  </li>
                  <li>
                    <b className="text-fg">EPS growth %</b> compares the latest quarter with the same quarter a year earlier
                    (reported figures), so one unusual quarter can make it jump.
                  </li>
                  <li>
                    Expensive is not the same as "will fall": markets sometimes pay more for a strong brand, a monopoly or future
                    plans. Use it as a question to research, not a verdict.
                  </li>
                </ul>
              </details>
            )}
            {results.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted">{etf ? 'No ETF' : crypto ? 'No coin' : 'No company'} passes every rule right now.</p>
            ) : (
              <ScrollBox className="overflow-x-auto">
                <table className="tabular w-full min-w-[40rem] text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="py-2 text-start font-medium">{etf ? 'ETF' : crypto ? 'Coin' : 'Company'}</th>
                      {!priceBased && <th className="px-2 py-2 text-end font-medium">Mkt cap</th>}
                      <th className="px-2 py-2 text-end font-medium">Price</th>
                      <th className="px-2 py-2 text-end font-medium">Day</th>
                      {data.columns.map((c) => (
                        <th key={c.key} className={cx('px-2 py-2 font-medium', c.key === 'sector' ? 'text-start' : 'text-end')}>{c.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {results.map((r) => (
                      <tr key={r.symbol}>
                        <td className="max-w-[14rem] py-2">
                          <Link to={`/analyze?symbol=${encodeURIComponent(r.symbol)}&market=${market}`} className="block truncate hover:text-accent-fg" title={r.name ?? r.symbol}>
                            <span className="font-mono text-xs font-medium">{r.symbol}</span>{' '}
                            <span className="text-xs text-muted">{english.name(r.symbol, r.name)}</span>
                          </Link>
                        </td>
                        {!priceBased && <td className="px-2 py-2 text-end">{compact(r.market_cap)}</td>}
                        <td className={cx('whitespace-nowrap px-2 py-2 text-end', ticking.flash(r))}>{price(r.price, r.currency)}</td>
                        <td className={cx('px-2 py-2 text-end', trendClass(r.change_percent))}>{pct(r.change_percent)}</td>
                        {data.columns.map((c) => (
                          <td key={c.key} className={cx('px-2 py-2', c.key === 'sector' ? 'max-w-[9rem] truncate text-start text-xs text-muted' : 'text-end')}>
                            {cell(c.key, r[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollBox>
            )}
            <p className="text-[12px] text-faint">
              {data.universe}; {data.scanned} had data.{' '}
              {crypto
                ? 'Daily prices from crypto exchange data.'
                : etf
                  ? 'Daily prices from the market data feed; returns are price only, before dividends.'
                  : 'Fundamentals from the market data feed, latest reported.'}{' '}
              A starting point for research, not a recommendation.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
