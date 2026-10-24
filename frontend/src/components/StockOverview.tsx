import { useEffect, useState, type ReactNode } from 'react'
import { getOverview, type OverviewItem, type StockOverview as Overview } from '../api/stocks'
import { cx } from '../lib/cx'
import { compact, errorMessage, num, pct, relativeTime, trendClass } from '../lib/format'
import LeadershipCard from './LeadershipCard'
import OwnershipCard from './OwnershipCard'
import MdnaCard from './MdnaCard'
import { Badge, Card, CardBody, CardHeader, SignalBadge, Skeleton } from './ui'

function fmtItem(item: OverviewItem): string {
  if (item.value == null) return '—'
  if (item.kind === 'pct') return `${num(item.value, 1)}%`
  if (item.kind === 'money') return compact(item.value)
  return num(item.value, 2)
}

function Missing({ text }: { text?: string }) {
  return <p className="text-xs text-faint">{text ? `Not available: ${text}` : 'Not available'}</p>
}

function Row({ label, value, hint, className }: { label: string; value: ReactNode; hint?: string; className?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5" title={hint}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={cx('tabular text-sm font-medium', className)}>{value}</dd>
    </div>
  )
}

export type OverviewPart =
  | 'technical' | 'fundamentals' | 'risk' | 'analysts' | 'profile'
  | 'leadership' | 'ownership' | 'mdna' | 'news'

const ALL_PARTS: OverviewPart[] = ['technical', 'fundamentals', 'risk', 'analysts', 'profile', 'leadership', 'ownership', 'mdna', 'news']

// One request per stock for every view that shows part of the overview; a
// failed one is dropped so the next view retries, and old ones expire.
const OVERVIEW_TTL = 5 * 60_000
const overviewCache = new Map<string, { at: number; promise: Promise<Overview> }>()

/** The overview for a stock, shared by all views (and warmed before one opens). */
export function loadOverview(symbol: string, market: string): Promise<Overview> {
  const key = `${symbol}:${market}`
  const hit = overviewCache.get(key)
  if (hit && Date.now() - hit.at < OVERVIEW_TTL) return hit.promise
  const promise = getOverview(symbol, market)
  promise.catch(() => overviewCache.delete(key))
  overviewCache.set(key, { at: Date.now(), promise })
  return promise
}

/** Everything the app computes about a stock - technicals, fundamentals,
 * risk, analysts, events, profile, news. Market data only, no AI.
 * `parts` picks which cards show (Analyze spreads them over its views). */
export default function StockOverview({
  symbol,
  market,
  investor = true,
  parts = ALL_PARTS,
}: {
  symbol: string
  market: string
  /** Business sections (fundamentals, leadership, ownership, MD&A); off in the Trader section. */
  investor?: boolean
  parts?: OverviewPart[]
}) {
  const has = (part: OverviewPart) => parts.includes(part)
  const needsData = (['technical', 'fundamentals', 'risk', 'analysts', 'profile', 'news'] as const).some(
    (part) => has(part) && (part !== 'fundamentals' || investor),
  )
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showFullSummary, setShowFullSummary] = useState(false)

  useEffect(() => {
    if (!needsData) return
    let cancelled = false
    setData(null)
    setError(null)
    loadOverview(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market, needsData])

  const grid = (['technical', 'fundamentals', 'risk', 'analysts'] as const).filter(
    (part) => has(part) && (part !== 'fundamentals' || investor),
  )

  return (
    <div className="space-y-6">
      {needsData &&
        (error ? (
          <Card>
            <CardBody>
              <Missing text={error} />
            </CardBody>
          </Card>
        ) : !data ? (
          <div className={cx('grid gap-6', grid.length > 1 && 'xl:grid-cols-2')}>
            {Array.from({ length: Math.max(1, grid.length) }, (_, i) => (
              <Skeleton key={i} className="h-56 w-full" />
            ))}
          </div>
        ) : (
          <OverviewSections data={data} symbol={symbol} grid={grid} has={has} showFullSummary={showFullSummary} onToggleSummary={() => setShowFullSummary((v) => !v)} />
        ))}

      {/* ------------------------------------------------ leadership */}
      {investor && has('leadership') && <LeadershipCard symbol={symbol} market={market} />}
      {investor && has('ownership') && market !== 'crypto' && <OwnershipCard symbol={symbol} market={market} />}
      {investor && has('mdna') && market === 'us' && <MdnaCard symbol={symbol} />}

      {has('news') && data && <NewsCard news={data.news} />}
    </div>
  )
}

function OverviewSections({
  data,
  symbol,
  grid,
  has,
  showFullSummary,
  onToggleSummary,
}: {
  data: Overview
  symbol: string
  grid: OverviewPart[]
  has: (part: OverviewPart) => boolean
  showFullSummary: boolean
  onToggleSummary: () => void
}) {
  const { technical: t, fundamentals: f, risk: r, analysts: a, events: e, profile: p } = data
  return (
    <>
      {grid.length > 0 && (
        <p className="text-xs text-faint">Market data computed by MarketMyna - facts, not AI opinion. Run AI for the AI read.</p>
      )}
      {grid.length > 0 && (
      <div className={cx('grid gap-6', grid.length > 1 && 'xl:grid-cols-2')}>
        {/* ------------------------------------------------ technical */}
        {grid.includes('technical') && (
        <Card id="section-technical" section="Technical">
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                Technical {t.overall && <SignalBadge value={t.overall} />}
              </span>
            }
            description={
              t.error
                ? undefined
                : t.counts
                  ? `${t.trend} · ${t.counts.buy} bullish / ${t.counts.sell} bearish / ${t.counts.neutral} neutral · as of ${t.as_of} · what the indicators read, not a recommendation`
                  : `${t.trend} · indicator values as of ${t.as_of}`
            }
          />
          <CardBody>
            {t.error ? (
              <Missing text={t.error} />
            ) : (
              <div className="space-y-4">
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-line">
                    {t.indicators.map((i) => (
                      <tr key={i.key} title={i.note}>
                        <td className="py-1.5 pe-2">
                          <div className="text-sm">{i.name}</div>
                          <div className="text-[12px] text-faint">{i.note}</div>
                        </td>
                        <td className="tabular py-1.5 pe-2 text-end">{num(i.value)}</td>
                        <td className="py-1.5 text-end">{i.signal && <SignalBadge value={i.signal} />}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {t.patterns && t.patterns.length > 0 && (
                  <div>
                    <div className="mb-1.5 text-xs font-medium text-muted">Patterns on the latest bar</div>
                    <div className="flex flex-wrap gap-1.5">
                      {t.patterns.map((p) => (
                        <span
                          key={p.key}
                          className={cx(
                            'rounded-md px-2 py-1 text-xs ring-1 ring-inset',
                            p.bias === 'bullish' ? 'bg-up-soft text-up ring-up/30' : p.bias === 'bearish' ? 'bg-down-soft text-down ring-down/30' : 'bg-canvas text-muted ring-line',
                          )}
                        >
                          {p.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <div className="mb-1.5 text-xs font-medium text-muted">Price vs moving averages</div>
                  <div className="flex flex-wrap gap-1.5">
                    {t.averages.map((m) => (
                      <span
                        key={m.period}
                        className={cx('rounded-md px-2 py-1 text-xs ring-1 ring-inset', m.above ? 'bg-up-soft text-up ring-up/30' : 'bg-down-soft text-down ring-down/30')}
                        title={`${m.period}-day average ${num(m.value)}`}
                      >
                        {m.period}D {pct(m.distance_pct, 1)}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="mb-1.5 text-xs font-medium text-muted">Returns</div>
                  <div className="grid grid-cols-5 gap-2 text-center">
                    {Object.entries(t.returns).map(([label, value]) => (
                      <div key={label} className="rounded-md bg-canvas py-1.5">
                        <div className="text-[12px] text-faint">{label}</div>
                        <div className={cx('tabular text-sm font-medium', trendClass(value))}>{pct(value, 1)}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <dl className="divide-y divide-line">
                  <Row label="52-week range" value={`${num(t.low_52w)} – ${num(t.high_52w)}`} />
                  <Row label="From 52-week high" value={pct(t.from_high_pct, 1)} className={trendClass(t.from_high_pct)} />
                </dl>
              </div>
            )}
          </CardBody>
        </Card>
        )}

        {/* ------------------------------------------------ fundamentals */}
        {grid.includes('fundamentals') && (
          <Card id="section-fundamentals" section="Fundamentals">
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  Fundamentals
                  {!f.error && <Badge tone={f.score >= 60 ? 'up' : f.score >= 40 ? 'warn' : 'down'}>{f.score}/100</Badge>}
                </span>
              }
              description={
                f.error
                  ? undefined
                  : [f.health_rating && `financial health ${f.health_rating}`, f.currency]
                      .filter(Boolean)
                      .join(' · ')
              }
            />
            <CardBody>
              {f.error ? (
                <Missing text={f.error} />
              ) : (
                <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                  {f.groups.map((g) => (
                    <div key={g.title}>
                      <div className="text-xs font-semibold tracking-wide text-faint uppercase">{g.title}</div>
                      <dl className="divide-y divide-line">
                        {g.items.map((item) => (
                          <Row key={item.label} label={item.label} value={fmtItem(item)} />
                        ))}
                      </dl>
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        )}

        {/* ------------------------------------------------ risk */}
        {grid.includes('risk') && (
        <Card id="section-risk" section="Risk">
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                Risk {!r.error && <SignalBadge value={r.level} />}
              </span>
            }
            description="Measured over the last year of daily prices"
          />
          <CardBody>
            {r.error ? (
              <Missing text={r.error} />
            ) : (
              <dl className="divide-y divide-line">
                <Row label="Volatility (annualised)" value={`${num(r.volatility_pct, 1)}%`} hint="How much the price typically swings in a year" />
                <Row label="Max drawdown" value={`${num(r.max_drawdown_pct, 1)}%`} className="text-down" hint="Largest peak-to-trough fall in the period" />
                <Row label="Beta" value={num(r.beta)} hint="Sensitivity to the overall market (1 = moves with it)" />
                <Row label="Best day" value={pct(r.best_day_pct, 1)} className="text-up" />
                <Row label="Worst day" value={pct(r.worst_day_pct, 1)} className="text-down" />
              </dl>
            )}
            {!r.error && r.realized && <VolatilityCones v={r.realized} />}
          </CardBody>
        </Card>
        )}

        {/* ------------------------------------------------ analysts & events */}
        {grid.includes('analysts') && (
        <Card id="section-analysts" section="Analysts & events">
          <CardHeader title="Analysts & upcoming events" />
          <CardBody className="space-y-4">
            {a.error ? (
              <Missing text={a.error} />
            ) : (
              <dl className="divide-y divide-line">
                {/* Third-party consensus as a direction; no price targets (src/core/compliance.py). */}
                <Row label="Broker consensus" value={<SignalBadge value={a.recommendation} />} />
                <Row label="Analysts" value={a.count ?? '—'} />
              </dl>
            )}
            {e.error ? (
              <Missing text={e.error} />
            ) : (
              <dl className="divide-y divide-line">
                <Row label="Next earnings" value={e.earnings_date ?? '—'} />
                <Row label="EPS estimate" value={num(e.eps_estimate)} />
                <Row label="Ex-dividend date" value={e.ex_dividend_date ?? '—'} />
                <Row label="Dividend payment" value={e.dividend_date ?? '—'} />
              </dl>
            )}
          </CardBody>
        </Card>
        )}
      </div>
      )}

      {/* ------------------------------------------------ profile */}
      {has('profile') && !p.error && (p.summary || p.sector) && (
        <Card id="section-profile" section="Company profile">
          <CardHeader
            title={p.name ?? symbol}
            description={[p.sector, p.industry, p.country, p.exchange].filter(Boolean).join(' · ')}
          />
          <CardBody className="space-y-3">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
              {p.employees != null && <span>{p.employees.toLocaleString()} employees</span>}
              {p.website && (
                <a href={p.website} target="_blank" rel="noreferrer" className="text-accent-fg hover:underline">
                  {p.website.replace(/^https?:\/\//, '')} ↗
                </a>
              )}
            </div>
            {p.summary && (
              <p className={cx('text-sm leading-relaxed text-fg/90', !showFullSummary && 'line-clamp-4')}>{p.summary}</p>
            )}
            {p.summary && p.summary.length > 400 && (
              <button type="button" onClick={onToggleSummary} className="text-xs text-accent-fg hover:underline">
                {showFullSummary ? 'Show less' : 'Read more'}
              </button>
            )}
          </CardBody>
        </Card>
      )}

    </>
  )
}

function NewsCard({ news: n }: { news: Overview['news'] }) {
  return (
    <Card id="section-news" section="Latest news">
      <CardHeader title="Latest news" />
      {n.error || !n.items?.length ? (
        <CardBody>
          <Missing text={n.error ?? 'no recent headlines found'} />
        </CardBody>
      ) : (
        <ul className="divide-y divide-line">
          {n.items.map((item) => (
            <li key={item.url || item.title}>
              <a
                href={item.url || undefined}
                target="_blank"
                rel="noreferrer"
                className="block px-5 py-3 hover:bg-raised/40"
              >
                <div className="text-sm font-medium">{item.title}</div>
                <div className="mt-0.5 text-xs text-muted">
                  {item.source}
                  {item.published && ` · ${relativeTime(item.published)}`}
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

const REGIME: Record<string, { label: string; className: string; note: string }> = {
  calm: { label: 'Calm', className: 'bg-up-soft text-up', note: 'Swings are smaller than usual for this stock' },
  normal: { label: 'Normal', className: 'bg-raised text-muted', note: 'Swings are in their usual range' },
  stormy: { label: 'Stormy', className: 'bg-down-soft text-down', note: 'Swings are larger than usual - size positions smaller' },
}

/** Realized volatility now vs its own history, per look-back window. */
function GarchForecast({ g }: { g: NonNullable<NonNullable<Overview['risk']['realized']>['garch']> }) {
  const month = g.forecasts.find((f) => f.days === 21) ?? g.forecasts[g.forecasts.length - 1]
  const dir = month.volatility > g.current * 1.05 ? 'rise' : month.volatility < g.current * 0.95 ? 'ease' : 'hold steady'
  return (
    <div className="rounded-lg bg-canvas p-3 text-xs">
      <div className="mb-2 font-medium text-muted">Forecast (GARCH)</div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <div className="text-faint">Now</div>
          <div className="tabular text-sm font-semibold">{num(g.current * 100, 1)}%</div>
        </div>
        {g.forecasts.map((f) => (
          <div key={f.days}>
            <div className="text-faint">Next {f.days === 21 ? 'month' : `${f.days} days`}</div>
            <div className="tabular text-sm font-semibold">{num(f.volatility * 100, 1)}%</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-faint">
        Expected to {dir}, pulling toward its long-run {num(g.long_run * 100, 1)}%
        {g.half_life_days != null ? `; shocks fade by half in about ${num(g.half_life_days, 0)} trading days` : ''}.
      </p>
    </div>
  )
}

function VolatilityCones({ v }: { v: NonNullable<Overview['risk']['realized']> }) {
  const regime = v.regime ? REGIME[v.regime] : null
  const max = Math.max(...v.cones.map((c) => Math.max(c.max, c.current)))
  const x = (value: number) => `${(value / max) * 100}%`
  return (
    <div className="mt-4 space-y-3 border-t border-line pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-medium text-muted">Volatility now vs its past year</div>
        {regime && (
          <span className={cx('rounded-md px-2 py-0.5 text-xs', regime.className)} title={regime.note}>
            {regime.label} · {num(v.percentile, 0)}th percentile
          </span>
        )}
      </div>
      <div className="space-y-2">
        {v.cones.map((c) => (
          <div key={c.window} className="grid grid-cols-[3rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-xs"
            title={`${c.window}-day: min ${num(c.min * 100, 1)}% · typical ${num(c.p25 * 100, 1)}-${num(c.p75 * 100, 1)}% · max ${num(c.max * 100, 1)}%`}>
            <span className="text-faint">{c.window}d</span>
            <span className="relative h-2.5 rounded-full bg-raised">
              <span className="absolute top-0 h-2.5 rounded-full bg-line-strong/60" style={{ left: x(c.min), width: `calc(${x(c.max)} - ${x(c.min)})` }} />
              <span className="absolute top-0 h-2.5 rounded-full bg-accent/40" style={{ left: x(c.p25), width: `calc(${x(c.p75)} - ${x(c.p25)})` }} />
              <span className="absolute -top-0.5 h-3.5 w-1 rounded-full bg-fg" style={{ left: `calc(${x(c.current)} - 2px)` }} />
            </span>
            <span className="tabular text-end">{num(c.current * 100, 1)}%</span>
          </div>
        ))}
      </div>
      <p className="text-[12px] text-faint">Bar = today's annualised volatility; shaded = its usual range (middle half) over the past year.</p>
      {v.garch && <GarchForecast g={v.garch} />}
      <details className="text-xs">
        <summary className="cursor-pointer text-muted">Estimators ({v.window}-day)</summary>
        <dl className="mt-1 divide-y divide-line">
          {v.estimators.map((e) => (
            <div key={e.key} className="flex justify-between py-1">
              <dt className="text-muted">{e.name}</dt>
              <dd className="tabular">{e.value == null ? '—' : `${num(e.value * 100, 1)}%`}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  )
}
