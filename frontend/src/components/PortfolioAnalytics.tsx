import { useEffect, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getPortfolioAnalytics, type PortfolioAnalytics as Analytics } from '../api/portfolio'
import { cx } from '../lib/cx'
import { compact, errorMessage, money, num, pct, trendClass } from '../lib/format'
import { chance, monthlyNeeded, project } from '../lib/montecarlo'
import { Alert, Button, Card, CardBody, CardHeader, Input, Segmented, Skeleton, Stat } from './ui'

/** Fractions (0.12) -> "+12.0%". */
const fpct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : pct(v * 100, digits))
const plain = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${num(v * 100, digits)}%`)
/** Whole currency units (projections, stress losses): paise / cents are noise here. */
function whole(v: number | null | undefined, currency: string): string {
  if (v == null || !Number.isFinite(v)) return '—'
  try {
    return v.toLocaleString(currency === 'INR' ? 'en-IN' : undefined, { style: 'currency', currency, maximumFractionDigits: 0 })
  } catch {
    return `${Math.round(v).toLocaleString()} ${currency}`
  }
}

type Tab = 'risk' | 'correlation' | 'stress' | 'projection'

const TABS = [
  { value: 'risk', label: 'Risk by holding' },
  { value: 'correlation', label: 'Correlation' },
  { value: 'stress', label: 'Stress test' },
  { value: 'projection', label: 'Projection & goal' },
]

export default function PortfolioAnalytics({ portfolio, currency, version }: { portfolio: string; currency: string; version: string }) {
  const [data, setData] = useState<Analytics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('risk')

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setData(await getPortfolioAnalytics(portfolio))
    } catch (err) {
      setData(null)
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  // Reload when the portfolio or its holdings change.
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolio, version])

  const m = data?.metrics
  return (
    <Card id="section-analytics" section="Risk & analytics">
      <CardHeader
        title="Risk & analytics"
        icon="analyze"
        description={
          data
            ? `Today's mix replayed over ${data.days} trading days to ${data.as_of}, vs ${data.benchmark.name}`
            : 'Return, risk and diversification of the current holdings over the last year'
        }
        actions={
          <Button variant="ghost" icon="refresh" loading={loading} onClick={load}>
            Recalculate
          </Button>
        }
      />
      <CardBody className="space-y-5">
        {error && <Alert tone="warn" title="Analytics unavailable">{error}</Alert>}
        {!data && !error && <Skeleton className="h-48 w-full" />}
        {data && m && (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-8">
              <Stat label="Annual return" value={<span className={trendClass(m.annual_return)}>{fpct(m.annual_return)}</span>}
                sub={m.benchmark_return != null ? `index ${fpct(m.benchmark_return)}` : undefined} />
              <Stat label="Volatility" value={plain(m.volatility)} sub="annualised" />
              <Stat label="Sharpe" value={num(m.sharpe)} sub={`rf ${plain(data.risk_free)}`} />
              <Stat label="Sortino" value={num(m.sortino)} sub="downside only" />
              <Stat label="Max drawdown" value={<span className="text-down">{fpct(m.max_drawdown)}</span>} />
              <Stat label="Beta" value={num(m.beta)} sub={data.benchmark.name} />
              <Stat label="1-day VaR 95%" value={money(m.var_95_value, currency)} sub={plain(m.var_95, 2)} />
              <Stat label="Expected shortfall" value={money(m.cvar_95_value, currency)} sub={plain(m.cvar_95, 2)} />
            </div>

            {m.tracking_error != null && (
              <div className="grid grid-cols-2 gap-4 rounded-lg bg-canvas px-3 py-2.5 sm:grid-cols-4">
                <Stat label="Tracking error" value={plain(m.tracking_error)} sub={`vs ${data.benchmark.name}, a year`} />
                <Stat label="Information ratio" value={num(m.information_ratio)} sub="extra return per unit of tracking error" />
                <Stat label="Up capture" value={plain(m.up_capture, 0)} sub="of the index's rises" />
                <Stat label="Down capture" value={plain(m.down_capture, 0)} sub="of the index's falls" />
              </div>
            )}

            {data.warnings.length > 0 && (
              <ul className="space-y-1 text-xs text-warn">
                {data.warnings.map((w) => <li key={w}>• {w}</li>)}
              </ul>
            )}

            {data.curve.length > 1 && (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.curve} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--color-line)" vertical={false} />
                    <XAxis dataKey="time" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false}
                      minTickGap={40} tickFormatter={(t) => new Date(t).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })} />
                    <YAxis domain={['auto', 'auto']} width={40} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                      formatter={(v, key) => [num(Number(v), 1), key === 'portfolio' ? 'Portfolio' : data.benchmark.name]}
                    />
                    <Legend formatter={(key) => (key === 'portfolio' ? 'Portfolio (start = 100)' : data.benchmark.name)} wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="portfolio" stroke="var(--color-accent)" strokeWidth={1.75} dot={false} />
                    <Line type="monotone" dataKey="benchmark" stroke="var(--color-faint)" strokeWidth={1.25} strokeDasharray="4 3" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            <Segmented
              value={tab}
              onChange={(v) => setTab(v as Tab)}
              options={TABS}
            />
            {tab === 'risk' && <RiskTable data={data} />}
            {tab === 'correlation' && <CorrelationGrid data={data} />}
            {tab === 'stress' && <StressTable data={data} currency={currency} />}
            {tab === 'projection' && <ProjectionPanel data={data} currency={currency} />}
          </>
        )}
      </CardBody>
    </Card>
  )
}

function RiskTable({ data }: { data: Analytics }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted">
          <tr>
            <th className="py-1.5 pe-2 text-start font-medium">Symbol</th>
            <th className="py-1.5 pe-2 text-end font-medium">Weight</th>
            <th className="py-1.5 pe-2 text-end font-medium" title="Share of total portfolio volatility">Risk share</th>
            <th className="py-1.5 pe-2 text-end font-medium">Return</th>
            <th className="py-1.5 pe-2 text-end font-medium">Volatility</th>
            <th className="py-1.5 pe-2 text-end font-medium">Max DD</th>
            <th className="py-1.5 text-end font-medium">Beta</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {data.holdings.map((h) => {
            const heavy = (h.risk_contribution ?? 0) > h.weight * 1.3
            return (
              <tr key={h.symbol}>
                <td className="py-1.5 pe-2 font-mono">{h.symbol}</td>
                <td className="tabular py-1.5 pe-2 text-end">{plain(h.weight)}</td>
                <td className={cx('tabular py-1.5 pe-2 text-end', heavy && 'font-semibold text-warn')}>{plain(h.risk_contribution)}</td>
                <td className={cx('tabular py-1.5 pe-2 text-end', trendClass(h.annual_return))}>{fpct(h.annual_return)}</td>
                <td className="tabular py-1.5 pe-2 text-end">{plain(h.volatility)}</td>
                <td className="tabular py-1.5 pe-2 text-end text-down">{fpct(h.max_drawdown)}</td>
                <td className="tabular py-1.5 text-end">{num(h.beta)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-faint">Risk share above weight (highlighted) means the holding adds more volatility than its size suggests.</p>
    </div>
  )
}

function CorrelationGrid({ data }: { data: Analytics }) {
  const { symbols, matrix } = data.correlation
  if (symbols.length < 2) return <p className="text-sm text-muted">Needs at least two holdings.</p>
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th />
            {symbols.map((s) => <th key={s} className="px-1.5 py-1 font-mono font-medium text-muted">{s}</th>)}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row, i) => (
            <tr key={row}>
              <th className="py-1 pe-2 text-start font-mono font-medium text-muted">{row}</th>
              {matrix[i].map((v, j) => {
                const c = v ?? 0
                const tone = c >= 0 ? 'var(--color-accent)' : 'var(--color-down)'
                return (
                  <td key={j} className="tabular px-1.5 py-1 text-center"
                    style={{ backgroundColor: `color-mix(in srgb, ${tone} ${Math.round(Math.abs(c) * 55)}%, transparent)` }}>
                    {v == null ? '—' : v.toFixed(2)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-faint">Daily-return correlation. Near 1 = move together (little diversification); near 0 or negative = diversify well.</p>
    </div>
  )
}

function StressTable({ data, currency }: { data: Analytics; currency: string }) {
  const rows = data.stress ?? []
  if (!rows.length) return <p className="text-sm text-muted">No stress scenarios for this portfolio.</p>
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-start text-xs text-muted">
              <th className="py-1 pe-3 font-medium">Scenario</th>
              <th className="py-1 pe-3 text-end font-medium">{data.benchmark.name}</th>
              <th className="py-1 text-end font-medium">This portfolio (est.)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-t border-line">
                <td className="py-1.5 pe-3">
                  {r.label}
                  {r.from && <div className="text-[11px] text-faint">{r.from} to {r.to}</div>}
                </td>
                <td className="tabular py-1.5 pe-3 text-end text-down">{fpct(r.index_move)}</td>
                <td className="tabular py-1.5 text-end text-down">
                  {fpct(r.portfolio_move)}
                  <div className="text-[11px]">{whole(r.portfolio_move * data.total_value, currency)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12px] text-faint">
        Past falls are the {data.benchmark.name}'s own peak-to-trough moves in each window; the portfolio estimate moves each holding by its beta
        (1 when unknown) times the index. Real losses differ: stocks fall unevenly and correlations rise in a crash.
      </p>
    </div>
  )
}

/** Monte Carlo projection with a goal: editable inputs, recomputed in the browser. */
function ProjectionPanel({ data, currency }: { data: Analytics; currency: string }) {
  const def = data.projection
  const [form, setForm] = useState({
    years: '10',
    monthly: '0',
    goal: String(Math.round(data.total_value * 2)),
    ret: ((def?.expected_return ?? 0.08) * 100).toFixed(1),
    vol: ((def?.volatility ?? 0.16) * 100).toFixed(1),
  })
  const parsed = {
    years: Math.min(40, Math.max(1, Math.round(Number(form.years) || 0))),
    monthly: Math.max(0, Number(form.monthly) || 0),
    goal: Math.max(0, Number(form.goal) || 0),
    ret: (Number(form.ret) || 0) / 100,
    vol: Math.max(0.01, (Number(form.vol) || 0) / 100),
  }
  const base = { start: data.total_value, years: parsed.years, expectedReturn: parsed.ret, volatility: parsed.vol }
  const result = useMemo(() => project({ ...base, monthly: parsed.monthly }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.total_value, parsed.years, parsed.monthly, parsed.ret, parsed.vol])
  const p = parsed.goal ? chance(result.finals, parsed.goal) : null
  const needed = useMemo(() => (parsed.goal ? monthlyNeeded(base, parsed.goal, 0.8) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.total_value, parsed.years, parsed.goal, parsed.ret, parsed.vol])
  const last = result.bands[result.bands.length - 1]
  const chart = result.bands.map((b) => ({ ...b, band: [b.p10, b.p90] as [number, number] }))
  const field = (key: keyof typeof form, label: string, suffix?: string) => (
    <label className="block min-w-0">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      <div className="flex items-center gap-1.5">
        <Input type="number" inputMode="decimal" value={form[key]} onChange={(ev) => setForm({ ...form, [key]: ev.target.value })} className="w-full" aria-label={label} />
        {suffix && <span className="text-sm text-muted">{suffix}</span>}
      </div>
    </label>
  )
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {field('years', 'Years')}
        {field('monthly', 'Added each month')}
        {field('goal', 'Goal')}
        {field('ret', 'Expected return', '%')}
        {field('vol', 'Volatility', '%')}
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label={`Middle outcome in ${parsed.years} years`} value={whole(last.p50, currency)} sub={`put in ${whole(last.invested, currency)}`} />
        <Stat label="Bad case (1 in 10)" value={whole(last.p10, currency)} sub="10th percentile" />
        <Stat label="Chance of reaching the goal" value={p != null ? `${Math.round(p * 100)}%` : '—'} sub={`goal ${whole(parsed.goal, currency)}`} />
        <Stat
          label="Monthly amount for an 80% chance"
          value={needed == null ? '—' : whole(needed, currency)}
          sub={needed === 0 ? 'already on track without adding' : 'at these return and volatility figures'}
        />
      </div>
      <div className="h-60">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chart} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--color-line)" vertical={false} />
            <XAxis dataKey="year" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(y) => `${y}y`} />
            <YAxis width={56} tickFormatter={(v: number) => compact(v)} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
              labelFormatter={(y) => `Year ${y}`}
              formatter={(v, key) => {
                if (Array.isArray(v)) return [`${whole(Number(v[0]), currency)} – ${whole(Number(v[1]), currency)}`, '1 in 10 to 9 in 10']
                return [whole(Number(v), currency), key === 'p50' ? 'Middle outcome' : 'Money put in']
              }}
            />
            <Area type="monotone" dataKey="band" stroke="none" fill="var(--color-accent)" fillOpacity={0.15} />
            <Line type="monotone" dataKey="p50" stroke="var(--color-accent)" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="invested" stroke="var(--color-faint)" strokeDasharray="4 3" dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[12px] text-faint">
        2,000 simulated paths with monthly returns drawn at your expected return and volatility (defaults: a long-run assumption for this market and
        this portfolio's own volatility over the past year), contributions added each month, no taxes or costs. Shaded: the middle 80% of
        outcomes. A projection of your inputs, not a forecast or advice.
      </p>
    </div>
  )
}
