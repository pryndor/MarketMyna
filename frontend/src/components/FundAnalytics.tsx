import { useEffect, useState, type ReactNode } from 'react'
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getFundAnalytics, type FundAnalytics as Data, type FundRisk, type RollingWindow } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num, pct } from '../lib/format'
import InsightLoader from './InsightLoader'
import { Alert } from './ui'

const FUND = 'var(--color-accent)'
const BENCH = 'var(--color-faint)'

const axis = { tick: { fill: 'var(--color-faint)', fontSize: 11 }, axisLine: false, tickLine: false }
const tooltip = {
  cursor: { stroke: 'var(--color-line-strong)' },
  contentStyle: { background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 },
}
const yearTick = (d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })

function months(days: number | null): string {
  if (days == null) return '—'
  if (days < 45) return `${days} days`
  const m = days / 30.44
  return m < 24 ? `${Math.round(m)} months` : `${num(m / 12, 1)} years`
}

function Section({ id, label, title, subtitle, children }: { id: string; label: string; title: string; subtitle: ReactNode; children: ReactNode }) {
  return (
    <section id={id} data-section={label} className="scroll-mt-6 space-y-4 border-t border-line pt-6">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="text-xs text-muted">{subtitle}</p>
      </div>
      {children}
    </section>
  )
}

function Metric({ label, value, sub, hint, tone }: { label: string; value: string; sub?: string; hint: string; tone?: 'up' | 'down' }) {
  return (
    <div className="rounded-lg bg-canvas p-3" title={hint}>
      <div className="text-xs text-faint">{label}</div>
      <div className={cx('tabular mt-0.5 text-base font-semibold', tone === 'up' && 'text-up', tone === 'down' && 'text-down')}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted">{sub}</div>}
    </div>
  )
}

function RollingTable({ rows, bench }: { rows: RollingWindow[]; bench: string | null }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-faint">
            <th className="py-1.5 pe-3 text-start font-medium">Window</th>
            <th className="px-2 py-1.5 text-end font-medium">Typical</th>
            <th className="px-2 py-1.5 text-end font-medium">Worst</th>
            <th className="px-2 py-1.5 text-end font-medium">Best</th>
            <th className="px-2 py-1.5 text-end font-medium" title="Share of start days that ended with a loss">Lost money</th>
            <th className="px-2 py-1.5 text-end font-medium" title="Share of start days that earned more than 12% a year">Over 12%</th>
            {bench && <th className="px-2 py-1.5 text-end font-medium">{bench} typical</th>}
            {bench && <th className="py-1.5 ps-2 text-end font-medium" title="Share of the same windows where the fund did better">Beat it</th>}
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((r) => (
            <tr key={r.years} className="border-t border-line">
              <td className="whitespace-nowrap py-2 pe-3 text-start">
                {r.years} year{r.years > 1 ? 's' : ''}
                <span className="block text-[11px] text-faint">{r.windows.toLocaleString()} start days</span>
              </td>
              <td className="px-2 py-2 text-end font-semibold">{pct(r.median, 1)}</td>
              <td className={cx('px-2 py-2 text-end', r.min < 0 ? 'text-down' : '')} title={`Starting ${r.worst_start}`}>{pct(r.min, 1)}</td>
              <td className="px-2 py-2 text-end text-up" title={`Starting ${r.best_start}`}>{pct(r.max, 1)}</td>
              <td className="px-2 py-2 text-end">{num(r.negative_pct, 0)}%</td>
              <td className="px-2 py-2 text-end">{num(r.above_12_pct, 0)}%</td>
              {bench && <td className="px-2 py-2 text-end text-muted">{pct(r.bench_median, 1)}</td>}
              {bench && (
                <td className={cx('py-2 ps-2 text-end font-semibold', r.beat_pct == null ? '' : r.beat_pct >= 50 ? 'text-up' : 'text-down')}>
                  {r.beat_pct == null ? '—' : `${num(r.beat_pct, 0)}%`}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RiskGrid({ r, bench }: { r: FundRisk; bench: string | null }) {
  const vs = (v: number | null, digits = 1) => (bench && v != null ? `${bench}: ${num(v * 100, digits)}%` : undefined)
  const hasBench = bench != null && r.beta != null
  // Sharpe / Sortino divide by volatility: meaningless for funds that barely move (liquid, overnight).
  const steady = r.volatility < 0.01
  const fall = Math.abs(r.max_drawdown) < 0.0005 ? 0 : r.max_drawdown
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Metric label="Return a year" value={`${num(r.annual_return * 100, 1)}%`} sub={vs(r.bench_annual_return)} hint="Annualised over the period" />
        <Metric label="Volatility" value={`${num(r.volatility * 100, 1)}%`} sub={vs(r.bench_volatility)} hint="How much the NAV swings in a year; lower is steadier" />
        <Metric label="Worst fall" value={`${num(fall * 100, 1)}%`} sub={vs(r.bench_max_drawdown)} hint="Biggest peak-to-trough fall in the period" tone={fall < 0 ? 'down' : undefined} />
        {!steady && (
          <>
            <Metric label="Sharpe" value={num(r.sharpe, 2)} hint={`Return above a ${num(r.risk_free, 1)}% risk-free rate per unit of volatility; above 1 is strong`} />
            <Metric label="Sortino" value={num(r.sortino, 2)} hint="Like Sharpe, but only counts downside swings" />
          </>
        )}
        {hasBench && (
          <>
            <Metric label="Beta" value={num(r.beta, 2)} sub={r.beta != null ? `Moves ${num(r.beta, 2)}× the index` : undefined} hint="1 = moves with the index; below 1 = calmer, above 1 = wilder" />
            <Metric label="Alpha a year" value={pct((r.alpha ?? 0) * 100, 1)} tone={(r.alpha ?? 0) >= 0 ? 'up' : 'down'} hint="Return beyond what its beta to the index explains (Jensen's alpha)" />
            <Metric label="Up capture" value={`${num((r.up_capture ?? 0) * 100, 0)}%`} hint="How much of the index's rising days the fund caught (100% = all of it)" />
            <Metric label="Down capture" value={`${num((r.down_capture ?? 0) * 100, 0)}%`} hint="How much of the index's falling days the fund took (lower is better)" />
            <Metric label="Tracking error" value={`${num((r.tracking_error ?? 0) * 100, 1)}%`} hint="How far its returns stray from the index in a year; tiny for index funds" />
            <Metric label="Information ratio" value={num(r.information_ratio, 2)} hint="Extra return per unit of tracking error; above 0.5 is good" />
          </>
        )}
      </div>
      {steady && (
        <p className="text-xs text-muted">
          The NAV barely moves, so Sharpe and Sortino (which divide by those moves) would be meaningless here. For a fund like this, compare its return a year
          against the {num(r.risk_free, 1)}% risk-free rate.
        </p>
      )}
      {hasBench && r.up_capture != null && r.down_capture != null && (
        <p className="text-xs text-muted">
          In plain words: on days the {bench} rose, this fund rose about {num(r.up_capture * 100, 0)}% as much; on days it fell, the fund fell about{' '}
          {num(r.down_capture * 100, 0)}% as much.{' '}
          {r.up_capture > r.down_capture
            ? 'It kept more of the gains than it took of the losses.'
            : 'It took relatively more of the losses than it kept of the gains.'}
        </p>
      )}
    </div>
  )
}

/** Rolling returns, risk against the category benchmark and drawdowns with
 * recovery times, from the fund's whole NAV history. */
export default function FundAnalytics({ code }: { code: string }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError(null)
    getFundAnalytics(code, controller.signal)
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [code])

  if (error)
    return (
      <Section id="fund-rolling" label="Rolling returns" title="Rolling returns" subtitle="Returns from every possible start day">
        <p className="text-xs text-faint">Unavailable right now: {error}</p>
      </Section>
    )
  if (!data)
    return (
      <Section id="fund-rolling" label="Rolling returns" title="Rolling returns" subtitle="Returns from every possible start day">
        <InsightLoader
          className="min-h-40"
          steps={['Reading the full NAV history…', 'Fetching the category benchmark…', 'Rolling every 1, 3 and 5-year window…', 'Measuring falls and recoveries…']}
        />
      </Section>
    )
  if (data.status !== 'ok' || !data.rolling || !data.drawdowns) return <p className="text-xs text-faint">{data.note}</p>

  const bench = data.benchmark?.available ? data.benchmark.name : null
  const rolling = data.rolling
  const dd = data.drawdowns
  const ddChart = dd.chart

  return (
    <>
      <Section
        id="fund-rolling"
        label="Rolling returns"
        title="Rolling returns"
        subtitle={`The yearly return from every possible start day since ${data.nav_from}: how consistent the fund has been, not just where it stands today.`}
      >
        {data.payout_option && (
          <Alert tone="warn">
            This is an IDCW (payout) option: each payout lowers the NAV, so every return here understates what investors earned. Compare the Growth option of the
            same scheme.
          </Alert>
        )}
        <RollingTable rows={rolling.windows} bench={bench} />
        {rolling.chart.length > 1 && (
          <div>
            <div className="mb-1 text-xs text-muted">{rolling.chart_years}-year rolling return, by start date</div>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rolling.chart} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--color-line)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={yearTick} minTickGap={48} {...axis} />
                  <YAxis orientation="right" width={44} tickFormatter={(v: number) => `${v}%`} {...axis} />
                  <ReferenceLine y={0} stroke="var(--color-line-strong)" />
                  <Tooltip {...tooltip} labelFormatter={(d) => `Start ${d}`} formatter={(v, name) => [`${num(Number(v), 1)}% a year`, name]} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="fund" name="This fund" stroke={FUND} strokeWidth={1.75} dot={false} />
                  {bench && <Line type="monotone" dataKey="bench" name={bench} stroke={BENCH} strokeWidth={1.25} dot={false} connectNulls />}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </Section>

      <Section
        id="fund-risk"
        label="Risk vs benchmark"
        title={bench ? `Risk against the ${bench}` : 'Risk'}
        subtitle={
          data.risk
            ? `Last ${data.risk.years} years of daily returns (since ${data.risk.from}).${bench ? '' : ' No free index matches this category, so it is measured on its own.'}`
            : 'Not enough history yet.'
        }
      >
        {data.risk && <RiskGrid r={data.risk} bench={bench} />}
      </Section>

      <Section
        id="fund-drawdowns"
        label="Drawdowns & recovery"
        title="Drawdowns & recovery"
        subtitle={`How far the NAV has fallen from its highs, and how long it took to get back. Now ${num(Math.abs(dd.current), 1)}% below its high; worst ever ${num(dd.max, 1)}%.`}
      >
        {dd.crashes.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-3">
            {dd.crashes.map((c) => (
              <div key={c.label} className="rounded-lg bg-canvas p-3">
                <div className="text-xs text-faint">{c.label}</div>
                <div className="tabular mt-0.5 text-base font-semibold text-down">{num(c.fund, 1)}%</div>
                {c.bench != null && (
                  <div className={cx('text-[11px]', c.fund > c.bench ? 'text-up' : 'text-muted')}>
                    {bench}: {num(c.bench, 1)}%{c.fund > c.bench ? ' · fell less' : ''}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {ddChart.length > 1 && (
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={ddChart} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--color-line)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={yearTick} minTickGap={48} {...axis} />
                <YAxis orientation="right" width={44} tickFormatter={(v: number) => `${v}%`} {...axis} />
                <Tooltip {...tooltip} formatter={(v, name) => [`${num(Number(v), 1)}% below high`, name]} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {bench && <Area type="monotone" dataKey="bench" name={bench} stroke={BENCH} fill="none" strokeWidth={1.25} connectNulls />}
                <Area type="monotone" dataKey="fund" name="This fund" stroke="var(--color-down)" fill="var(--color-down)" fillOpacity={0.15} strokeWidth={1.5} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
        {dd.episodes.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-faint">
                  <th className="py-1.5 pe-3 text-start font-medium">Fall</th>
                  <th className="px-2 py-1.5 text-start font-medium">From high</th>
                  <th className="px-2 py-1.5 text-start font-medium">To low</th>
                  <th className="px-2 py-1.5 text-end font-medium">Falling for</th>
                  <th className="py-1.5 ps-2 text-end font-medium">Back to the high</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {dd.episodes.map((e) => (
                  <tr key={e.peak} className="border-t border-line">
                    <td className="py-2 pe-3 text-start font-semibold text-down">{num(e.depth, 1)}%</td>
                    <td className="px-2 py-2 text-start">{e.peak}</td>
                    <td className="px-2 py-2 text-start">{e.trough}</td>
                    <td className="px-2 py-2 text-end">{months(e.days_down)}</td>
                    <td className="py-2 ps-2 text-end">{e.recovered ? `${months(e.days_to_recover)} (${e.recovered})` : <span className="text-warn">Not yet</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-faint">
          {data.note}
          {data.benchmark?.dividend_yield != null && ` Dividends added to the ${data.benchmark.name}: ${num(data.benchmark.dividend_yield, 2)}% a year.`}
        </p>
      </Section>
    </>
  )
}
