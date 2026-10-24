import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getIndiaFlows, type IndiaFlows as Data, type ParticipantPosition } from '../api/macro'
import { cx } from '../lib/cx'
import { trendClass } from '../lib/format'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'


const TIP = { background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }

const crore = (v: number | null | undefined) =>
  v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`
const contracts = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toLocaleString('en-IN')}`
const short = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

/** FII / DII cash flows and who is long or short index derivatives (NSE). */
export default function IndiaFlows() {
  // Published once a day after the close: look for the new day's figures.
  const { data, error, at } = useInsight((signal) => getIndiaFlows(signal), [], DAILY_EVERY)

  const c = data?.cash
  const p = data?.positioning
  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">FII / DII flows</h2>
        <p className="text-xs text-muted">Foreign and domestic institutions' buying and selling, and who is long or short the index</p>
        <InsightLive at={at} daily="New figures each trading evening" />
      </div>
      <div className="space-y-5 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Fetching NSE cash flows…', 'Reading participant open interest…']} />}

        {c?.latest && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-muted">Cash market · {short(c.latest.date)}</span>
              {c.stale && <span className="text-xs text-warn">{c.stale}</span>}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {(['fii', 'dii'] as const).map((k) => {
                const side = c.latest?.[k]
                return (
                  <div key={k} className="rounded-lg bg-canvas px-3 py-2">
                    <div className="text-xs text-muted">{k === 'fii' ? 'Foreign institutions (FII / FPI)' : 'Domestic institutions (DII)'}</div>
                    <div className={cx('tabular text-lg font-semibold', trendClass(side?.net))}>{crore(side?.net)}</div>
                    <div className="tabular text-[11px] text-faint">
                      bought ₹{side?.buy?.toLocaleString('en-IN', { maximumFractionDigits: 0 }) ?? '—'} cr · sold ₹
                      {side?.sell?.toLocaleString('en-IN', { maximumFractionDigits: 0 }) ?? '—'} cr
                    </div>
                    <div className="tabular mt-1 text-[11px] text-muted">
                      {c.five_day.sessions > 1 && (
                        <>
                          last {c.five_day.sessions} sessions <span className={trendClass(c.five_day[k])}>{crore(c.five_day[k])}</span> ·{' '}
                        </>
                      )}
                      month so far <span className={trendClass(c.month_to_date[k])}>{crore(c.month_to_date[k])}</span>
                      {c.month_to_date.sessions > 0 && ` (${c.month_to_date.sessions} session${c.month_to_date.sessions > 1 ? 's' : ''})`}
                    </div>
                  </div>
                )
              })}
            </div>
            {c.series.length > 1 ? (
              <div className="h-44 rounded-lg bg-canvas p-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={c.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--color-line)" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={short} tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={16} />
                    <YAxis orientation="right" width={64} tickFormatter={(v: number) => `${Math.round(v).toLocaleString('en-IN')}`} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={TIP} labelFormatter={(d) => short(String(d))} formatter={(v, n) => [crore(Number(v)), n === 'fii' ? 'FII' : 'DII']} />
                    <Bar dataKey="fii" fill="var(--color-accent)" />
                    <Bar dataKey="dii" fill="var(--color-warn)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-[12px] text-faint">
                NSE publishes only the latest session; the daily history here starts from the first saved day and grows each session.
              </p>
            )}
          </div>
        )}

        {p && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-muted">Index derivatives positioning · {short(p.date)}</span>
              <span className="text-xs text-faint">open contracts, last {p.sessions} sessions</span>
            </div>
            <FiiGauge p={p} />
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="text-start text-xs text-muted">
                    <th className="py-1 pe-3 font-medium">Participant</th>
                    <th className="py-1 pe-3 text-end font-medium">Index futures long</th>
                    <th className="py-1 pe-3 text-end font-medium">Net futures</th>
                    <th className="py-1 pe-3 text-end font-medium" title="Calls bought + puts sold, minus puts bought + calls sold">
                      Net index options
                    </th>
                    <th className="py-1 text-end font-medium">Change in net futures</th>
                  </tr>
                </thead>
                <tbody>
                  {(['FII', 'DII', 'Client', 'Pro'] as const).map((g) => {
                    const v: ParticipantPosition | undefined = p.groups[g]
                    if (!v) return null
                    const prev = p.previous?.[g]
                    const chg = prev ? v.index_futures_net - prev.index_futures_net : null
                    return (
                      <tr key={g} className="border-t border-line">
                        <td className="py-1.5 pe-3">{g === 'Client' ? 'Retail & others (client)' : g === 'Pro' ? 'Brokers (pro)' : g}</td>
                        <td className="tabular py-1.5 pe-3 text-end">{v.index_futures_long_pct != null ? `${v.index_futures_long_pct}%` : '—'}</td>
                        <td className={cx('tabular py-1.5 pe-3 text-end', trendClass(v.index_futures_net))}>{contracts(v.index_futures_net)}</td>
                        <td className={cx('tabular py-1.5 pe-3 text-end', trendClass(v.index_options_net))}>{contracts(v.index_options_net)}</td>
                        <td className={cx('tabular py-1.5 text-end', trendClass(chg))}>{chg != null ? contracts(chg) : '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {data && (
          <p className="text-[12px] text-faint">
            Source: {data.source}. Cash figures are NSE's provisional numbers for the session. Positioning counts open contracts; every long has a
            short on the other side, so one group's long is another's short. Shows how positions stand, not where the market will go.
          </p>
        )}
      </div>
    </div>
  )
}

/** FII index-futures long share: where today sits in the window, with the trend. */
function FiiGauge({ p }: { p: NonNullable<Data['positioning']> }) {
  const fii = p.groups.FII
  const pct = fii?.index_futures_long_pct
  const [lo, hi] = p.fii_long_pct_range ?? [0, 100]
  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <div className="rounded-lg bg-canvas px-3 py-2">
        <div className="text-xs text-muted">FII index futures held long</div>
        <div className="tabular text-2xl font-semibold">{pct != null ? `${pct}%` : '—'}</div>
        <div className="mt-1 text-[11px] text-faint">
          {fii && `${fii.index_futures_long.toLocaleString('en-IN')} long · ${fii.index_futures_short.toLocaleString('en-IN')} short`}
        </div>
        <div className="mt-1 text-[11px] text-muted">
          {p.sessions}-session range {lo}%–{hi}%.{' '}
          {pct != null && (pct < 30 ? 'Heavily short.' : pct > 70 ? 'Heavily long.' : 'Neither side dominant.')}
        </div>
      </div>
      <div className="h-32 rounded-lg bg-canvas p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={p.fii_long_pct_series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" tickFormatter={short} tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={24} />
            <YAxis orientation="right" width={40} domain={[(lo2: number) => Math.max(0, Math.floor(lo2 - 2)), (hi2: number) => Math.min(100, Math.ceil(hi2 + 2))]} allowDecimals={false} tickFormatter={(v: number) => `${v}%`} tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={TIP} labelFormatter={(d) => short(String(d))} formatter={(v) => [`${v}%`, 'FII long share']} />
            <Line type="monotone" dataKey="pct" stroke="var(--color-accent)" dot={false} strokeWidth={1.8} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
