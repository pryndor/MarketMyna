import { Line, LineChart, ResponsiveContainer, YAxis } from 'recharts'
import { getMarketRates, type MarketRates, type RateItem } from '../api/macro'
import { cx } from '../lib/cx'
import { num } from '../lib/format'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'

const SUBTITLE: Record<string, string> = {
  us: 'Fed and money-market rates, Treasury yields, and gold / silver in dollars',
  hong_kong: 'HKMA base rate, HIBOR, the HK dollar peg, and gold / silver in HK dollars',
  china_a: 'Interbank rates, the yuan, and gold / silver in yuan',
  crypto: "Perpetual funding rates (crypto's cost of leverage) and Bitcoin priced in gold",
}

const STEPS: Record<string, string[]> = {
  us: ['Reading official Fed and Treasury rates…', 'Fetching gold and silver futures…'],
  hong_kong: ['Reading HKMA base rate and HIBOR…', 'Checking the HK dollar peg…', 'Pricing gold per tael…'],
  china_a: ['Reading interbank rates…', 'Converting gold to yuan…'],
  crypto: ['Reading perpetual funding rates…', 'Pricing Bitcoin in gold…'],
}

function change(i: RateItem, v: number | null) {
  if (v == null) return null
  const text = i.change_kind === 'pct' ? `${v > 0 ? '+' : ''}${num(v, 1)}%` : `${v > 0 ? '+' : ''}${num(v, 2)}`
  return <span className={cx('tabular', v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-muted')}>{text}</span>
}

function format(i: RateItem) {
  if (i.unit === '%' || i.unit === '% / yr') return `${num(i.value, i.unit === '%' ? 2 : 1)}%`
  if (i.unit === 'pts') return `${i.value > 0 ? '+' : ''}${num(i.value, 2)}`
  if (i.unit === 'x' || i.unit === 'oz') return `${num(i.value, 1)}${i.unit === 'x' ? '×' : ' oz'}`
  const digits = Math.abs(i.value) >= 1000 ? 0 : Math.abs(i.value) >= 20 ? 2 : 4
  return `${i.unit}${i.value.toLocaleString(undefined, { maximumFractionDigits: digits })}`
}

function Stat({ i }: { i: RateItem }) {
  const spark = i.spark.map((v, idx) => ({ idx, v }))
  return (
    <div className="rounded-lg bg-canvas px-3 py-2.5" title={i.note || undefined}>
      <div className="truncate text-xs text-muted">{i.label}</div>
      <div className="flex items-end justify-between gap-2">
        <div className={cx('tabular text-lg font-semibold', i.tone === 'up' && 'text-up', i.tone === 'down' && 'text-down')}>
          {format(i)}
        </div>
        {spark.length > 4 && (
          <div className="h-7 w-20 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={spark}>
                <YAxis hide domain={['dataMin', 'dataMax']} />
                <Line dataKey="v" stroke="var(--color-accent)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
      {(i.change_1m != null || i.change_1y != null) && (
        <div className="mt-0.5 flex gap-3 text-[12px] text-faint">
          {i.change_1m != null && <span>1m {change(i, i.change_1m)}</span>}
          {i.change_1y != null && <span>1y {change(i, i.change_1y)}</span>}
        </div>
      )}
      {i.note && <div className="mt-1 line-clamp-2 text-[12px] text-faint">{i.note}</div>}
    </div>
  )
}

/** Rates & bullion for US, Hong Kong, China A and crypto (India has IndiaRatesCard). */
export default function RatesCard({ market }: { market: string }) {
  const { data, error, at } = useInsight<MarketRates>((signal) => getMarketRates(market, signal), [market], DAILY_EVERY)

  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">{data?.title ?? 'Rates & bullion'}</h2>
        <p className="text-xs text-muted">{SUBTITLE[market] ?? ''}</p>
        <InsightLive at={at} daily="Rates daily, prices hourly" />
      </div>
      <div className="space-y-6 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={STEPS[market] ?? ['Loading rates…']} />}
        {data?.errors.map((e) => (
          <p key={e} className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">{e}</p>
        ))}
        {data?.sections.map((s) => (
          <div key={s.title}>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-muted">{s.title}</span>
              {s.source && <span className="text-[12px] text-faint">{s.source}</span>}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {s.items.map((i) => (
                <Stat key={i.label} i={i} />
              ))}
            </div>
            {s.note && <p className="mt-2 text-[12px] text-faint">{s.note}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}
