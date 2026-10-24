import { getMarketMood } from '../api/macro'
import { cx } from '../lib/cx'
import { liveEvery, useFlash, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'


// Zones of the familiar fear & greed scale; neutral tones so the gauge reads
// as a description of the market, not a buy / sell signal.
const ZONES = [
  { to: 25, label: 'Extreme fear' },
  { to: 45, label: 'Fear' },
  { to: 55, label: 'Neutral' },
  { to: 75, label: 'Greed' },
  { to: 100, label: 'Extreme greed' },
]

function Bar({ score, big = false }: { score: number; big?: boolean }) {
  return (
    <div className={big ? 'relative h-3' : 'relative h-1.5'}>
      <div className="absolute inset-0 overflow-hidden rounded-full" style={{ background: 'linear-gradient(90deg, var(--color-down), var(--color-warn) 50%, var(--color-up))', opacity: 0.35 }} />
      <div
        className={cx(
          'absolute -translate-x-1/2 rounded-full bg-fg transition-[left] duration-700',
          big ? '-top-1 h-5 w-1.5' : '-top-0.5 h-2.5 w-1',
        )}
        style={{ left: `${score}%` }}
      />
    </div>
  )
}

/** Fear-to-greed gauge from breadth, moving averages, highs / lows, momentum and volatility. */
export default function MarketMood({ market }: { market: string }) {
  // Every reading is recomputed on live prices by the server.
  const { data, error, at } = useInsight((signal) => getMarketMood(market, signal), [market], liveEvery(30_000))
  const flash = useFlash(
    Object.fromEntries([['score', data?.score], ...(data?.readings ?? []).map((r) => [r.key, Math.round(r.score)])]),
  )

  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">Market mood</h2>
        <p className="text-xs text-muted">How broad the buying or selling is, from fear (0) to greed (100)</p>
        {data && <InsightLive live={data.live} at={at} />}
      </div>
      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && (
          <InsightLoader
            className="min-h-56"
            steps={
              market === 'crypto'
                ? ['Loading six months of prices for the most-traded coins…', 'Counting moving averages and highs…', 'Reading funding rates…']
                : ['Loading a year of prices for the largest stocks…', 'Counting moving averages and highs…', 'Reading the volatility index…']
            }
          />
        )}
        {data && data.score != null && (
          <>
            <div className="rounded-lg bg-canvas px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="flex items-baseline gap-2">
                  <span className={cx('tabular rounded text-3xl font-semibold', flash('score'))}>{Math.round(data.score)}</span>
                  <span className="text-base font-medium">{data.label}</span>
                </div>
                <span className="text-xs text-faint">average of {data.readings.length} readings</span>
              </div>
              <div className="mt-3">
                <Bar score={data.score} big />
                <div className="mt-1.5 hidden justify-between text-[11px] text-faint sm:flex">
                  {ZONES.map((z) => <span key={z.label}>{z.label}</span>)}
                </div>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {data.readings.map((r) => (
                <div key={r.key} className="rounded-lg border border-line px-3 py-2">
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="text-muted">{r.label}</span>
                    <span className={cx('tabular shrink-0 rounded font-semibold', flash(r.key))}>{Math.round(r.score)}</span>
                  </div>
                  <div className="tabular mb-1.5 text-[12px]">{r.value}</div>
                  <Bar score={r.score} />
                  <div className="mt-1 text-[11px] text-faint">{r.label_text}</div>
                </div>
              ))}
            </div>
            <p className="text-[12px] text-faint">
              Universe: {data.universe}; momentum uses the {data.index}. Each reading is scaled 0-100 and the gauge is their plain average. Source:{' '}
              {data.source}. A description of how the market is behaving now, not a forecast or advice.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
