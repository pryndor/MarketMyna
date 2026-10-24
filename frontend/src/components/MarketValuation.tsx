import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts'
import { getMarketValuation, type MarketValuation as Data, type ValuationSeries } from '../api/macro'
import { num } from '../lib/format'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'

import InsightLoader from './InsightLoader'

/** Whole-market valuation against its own history: S&P 500 since 1871, Nifty indices from NSE. */
export default function MarketValuation({ market }: { market: string }) {
  const { data, error, at } = useInsight((signal) => getMarketValuation(signal), [], DAILY_EVERY)

  const india = data && data.india.indices.length > 0 ? <India data={data} /> : null
  const us = data && data.us.series.length > 0 ? <Us data={data} /> : null

  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">Market valuation</h2>
        <p className="text-xs text-muted">How the whole market is priced today, against its own history</p>
        <InsightLive at={at} daily="Valuations update once a day" />
      </div>
      <div className="space-y-5 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Reading S&P 500 history…', 'Reading Nifty valuations…']} />}
        {market === 'india' || market === 'all' ? (
          <>
            {india}
            {us}
          </>
        ) : (
          <>
            {us}
            {india}
          </>
        )}
        {data && (
          <p className="text-[12px] text-faint">
            A percentile says where today's reading sits in the record (90th = higher than 90% of past months). It describes
            the past; it is not a forecast.
          </p>
        )}
      </div>
    </div>
  )
}

function Bar({ value }: { value: number | null }) {
  if (value == null) return null
  return (
    <div className="mt-1 h-1.5 rounded-full bg-line" title={`${value}th percentile`}>
      <div className="h-1.5 rounded-full bg-accent" style={{ width: `${Math.max(2, value)}%` }} />
    </div>
  )
}

function Us({ data }: { data: Data }) {
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-muted">S&amp;P 500 (US)</div>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.us.series.map((s) => (
          <UsTile key={s.key} s={s} />
        ))}
      </div>
      <p className="mt-2 text-[12px] text-faint">
        Source: {data.us.source}. Values marked ~ are estimates for the current month.
        {data.us.failed.length > 0 && ` Unavailable now: ${data.us.failed.join(', ')}.`}
      </p>
    </div>
  )
}

function UsTile({ s }: { s: ValuationSeries }) {
  const pctSuffix = s.key.includes('yield') ? '%' : ''
  return (
    <div className="rounded-lg bg-canvas px-3 py-2" title={s.note}>
      <div className="flex justify-between gap-2 text-xs text-muted">
        <span className="truncate">{s.label}</span>
        <span className="shrink-0 text-faint">{s.stale ? 'saved copy · ' : ''}{s.date}</span>
      </div>
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="tabular text-lg font-semibold">
            {s.estimated ? '~' : ''}
            {num(s.value, 2)}
            {pctSuffix}
          </div>
          <div className="tabular text-[11px] text-faint">
            {s.percentile_all != null && `${Math.round(s.percentile_all)}th pct since ${s.since.slice(0, 4)}`}
            {s.percentile_1990 != null && ` · ${Math.round(s.percentile_1990)}th since 1990`}
          </div>
          <Bar value={s.percentile_all} />
          <div className="tabular mt-1 text-[11px] text-faint">
            Median {num(s.median_all, 1)}
            {pctSuffix} all-time · {num(s.median_1990, 1)}
            {pctSuffix} since 1990
          </div>
        </div>
        <div className="h-12 w-20 shrink-0 sm:w-24">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={s.spark} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
              <YAxis hide domain={['auto', 'auto']} />
              <Area type="monotone" dataKey="value" stroke="var(--color-accent)" strokeWidth={1.5} fill="var(--color-accent)" fillOpacity={0.12} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

/** NIFTY NEXT 50 -> Nifty Next 50 */
function indexName(name: string): string {
  return name
    .toLowerCase()
    .replace(/\b[a-z]/g, (c) => c.toUpperCase())
}

function India({ data }: { data: Data }) {
  const rows = data.india.indices
  const building = rows.length > 0 && rows[0].pe_percentile == null
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-muted">Nifty indices (India)</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-start text-xs text-muted">
              <th className="py-1 pe-3 font-medium">Index</th>
              <th className="py-1 pe-3 text-end font-medium">P/E</th>
              <th className="py-1 pe-3 text-end font-medium">P/B</th>
              <th className="py-1 pe-3 text-end font-medium">Yield</th>
              <th className="py-1 text-end font-medium">P/E 1y ago</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.index} className="border-t border-line">
                <td className="py-1.5 pe-3">{indexName(r.index)}</td>
                <td className="tabular py-1.5 pe-3 text-end">
                  {num(r.pe, 2)}
                  {r.pe_percentile != null && <span className="text-[11px] text-faint"> · {Math.round(r.pe_percentile)}th</span>}
                </td>
                <td className="tabular py-1.5 pe-3 text-end">{num(r.pb, 2)}</td>
                <td className="tabular py-1.5 pe-3 text-end">{r.dy != null ? `${num(r.dy, 2)}%` : '—'}</td>
                <td className="tabular py-1.5 text-end text-muted">{r.pe_year_ago != null ? num(r.pe_year_ago, 2) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[12px] text-faint">
        Source: {data.india.source}
        {data.india.stale ? ' (NSE did not answer; showing the last saved day)' : ''}.
        {building &&
          ` Percentiles appear once a year of daily history has been saved (${rows[0].history_days} day${rows[0].history_days === 1 ? '' : 's'} so far).`}
      </p>
    </div>
  )
}
