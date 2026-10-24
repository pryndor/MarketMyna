import { Link } from 'react-router-dom'
import { getCrudeSensitivity, type CrudeSensitivity as Data } from '../api/macro'
import { cx } from '../lib/cx'
import { num, pct, trendClass } from '../lib/format'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import { ScrollBox } from './ui'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'

const SCALE = 0.5 // bar full width = |beta| 0.5

/** Diverging bar: left (red) = falls when crude rises, right (green) = rises with crude. */
function BetaBar({ beta, significant }: { beta: number; significant: boolean }) {
  const w = Math.min(Math.abs(beta) / SCALE, 1) * 50
  return (
    <span className="relative block h-2.5 w-full rounded-full bg-raised">
      <span className="absolute top-0 left-1/2 h-2.5 w-px bg-line-strong" />
      <span
        className={cx('absolute top-0 h-2.5 rounded-full', beta >= 0 ? 'bg-up' : 'bg-down', !significant && 'opacity-35')}
        style={beta >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
      />
    </span>
  )
}

const MARKET_NOUN: Record<string, string> = { india: 'Indian', us: 'US', hong_kong: 'Hong Kong', china_a: 'China A-share' }

/** How oil-linked stocks have moved with crude in local currency, net of the market. */
export default function CrudeSensitivity({ market = 'india' }: { market?: string } = {}) {
  const linkMarket = market === 'all' ? 'india' : market
  // Two years of weekly moves: a new day barely shifts it, so check rarely.
  const { data, error, at } = useInsight<Data>((signal) => getCrudeSensitivity(linkMarket, signal), [linkMarket], DAILY_EVERY)

  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Oil sensitivity</h2>
          <p className="text-xs text-muted">Which {MARKET_NOUN[linkMarket] ?? ''} stocks gain or lose when crude moves, beyond the market's own swing</p>
          <InsightLive at={at} daily="Weekly moves over two years, refreshed daily" />
        </div>
      </div>
      <div className="space-y-5 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Loading two years of weekly prices…', linkMarket === 'us' ? 'Lining up WTI crude…' : 'Converting crude to local currency…', 'Separating the oil effect from the market\'s swing…', 'Grouping stocks by how crude hits them…']} />}
        {data?.error && <p className="text-sm text-muted">{data.error}</p>}
        {data && data.groups.length > 0 && (
          <>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
              <span>
                {data.crude_label} <span className="tabular font-semibold">{data.currency}{num(data.crude, 0)}/bbl</span>
              </span>
              <span className="text-muted">
                1 month <span className={cx('tabular', trendClass(data.crude_change_1m))}>{pct(data.crude_change_1m, 1)}</span>
              </span>
              <span className="text-muted">
                1 year <span className={cx('tabular', trendClass(data.crude_change_1y))}>{pct(data.crude_change_1y, 1)}</span>
              </span>
            </div>

            <ScrollBox className="space-y-4 pe-1" maxHeight="62rem">
              {data.groups.map((g) => (
                <div key={g.name}>
                  <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="text-xs font-medium">{g.name}</span>
                    <span className="text-xs text-faint">{g.why}</span>
                  </div>
                  <div className="divide-y divide-line rounded-lg bg-canvas px-3">
                    {g.stocks.map((s) => (
                      <div key={s.symbol} className="grid grid-cols-[minmax(0,1fr)_5rem_3.5rem] items-center gap-3 py-2 text-sm sm:grid-cols-[12rem_minmax(0,1fr)_4rem_7rem]">
                        <Link to={`/analyze?symbol=${s.symbol}&market=${linkMarket}`} className="min-w-0 truncate hover:text-accent-fg" title={s.name}>
                          <span className="font-mono text-xs font-medium">{s.symbol}</span>{' '}
                          <span className="hidden text-xs text-muted sm:inline">{s.name}</span>
                        </Link>
                        <span title={`Crude beta ${num(s.beta_crude, 2)} (t ${num(s.t_crude, 1)}${s.significant ? '' : ', not significant'})`}>
                          <BetaBar beta={s.beta_crude} significant={s.significant} />
                        </span>
                        <span className={cx('tabular text-end text-xs', s.significant ? 'text-fg' : 'text-faint')}>
                          {s.beta_crude > 0 ? '+' : ''}{num(s.beta_crude, 2)}
                        </span>
                        <span className="tabular hidden text-end text-xs sm:inline" title="Crude's move last month times this stock's crude beta, market held flat">
                          {s.crude_implied_1m == null ? '—' : (
                            <span className={trendClass(s.crude_implied_1m)}>{pct(s.crude_implied_1m, 1)}</span>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </ScrollBox>
            <p className="text-[12px] text-faint">
              Crude beta: % move in the stock for a 1% move in {data.crude_label}, after removing what the {data.index_name} explains. -0.2 means
              a 10% oil jump has gone with about 2% underperformance. Faded bars are not statistically significant (|t| &lt; 2).
              Right column: what last month's oil move alone implies. {data.method} Past relationships; not investment advice.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
