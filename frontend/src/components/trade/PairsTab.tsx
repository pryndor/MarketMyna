import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getPairs, type PairsResult } from '../../api/trade'
import { cx } from '../../lib/cx'
import { errorMessage, num } from '../../lib/format'
import SymbolSearch from '../SymbolSearch'
import { Button, Card, CardBody, CardHeader, EmptyState, Field, Segmented } from '../ui'

const PERIODS = [
  { value: '1y', label: '1Y' },
  { value: '2y', label: '2Y' },
  { value: '5y', label: '5Y' },
]

const VERDICT = {
  cointegrated: { title: 'Cointegrated', className: 'bg-up-soft text-up' },
  stretched: { title: 'Cointegrated, spread stretched', className: 'bg-warn-soft text-warn' },
  not_cointegrated: { title: 'Not cointegrated', className: 'bg-raised text-muted' },
}

/** Engle-Granger pairs test: do two prices drift back together, and how far apart are they now? */
export default function PairsTab({ symbol, market }: { symbol: string; market: string }) {
  const [a, setA] = useState(symbol)
  const [marketA, setMarketA] = useState(market)
  const [b, setB] = useState('')
  const [marketB, setMarketB] = useState(market)
  const [period, setPeriod] = useState('2y')
  const [data, setData] = useState<PairsResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function run() {
    if (!a.trim() || !b.trim()) return
    setLoading(true)
    setError(null)
    try {
      setData(await getPairs({ a, b, market: marketA, market_b: marketB, period }))
    } catch (err) {
      setData(null)
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const v = data ? VERDICT[data.verdict] : null
  const side = data && Math.abs(data.z_now) >= 2
    ? data.z_now > 0
      ? `${data.a} is rich vs ${data.b}`
      : `${data.a} is cheap vs ${data.b}`
    : null

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Pairs test" description="Do two prices move apart and come back? (Engle-Granger cointegration)" icon="analyze" />
        <CardBody>
          <form
            className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end"
            onSubmit={(e) => {
              e.preventDefault()
              run()
            }}
          >
            <Field label="Symbol A">
              <SymbolSearch value={a} onChange={setA} onSelect={(r) => (setA(r.symbol), setMarketA(r.market))} placeholder="e.g. KO" />
            </Field>
            <Field label="Symbol B">
              <SymbolSearch value={b} onChange={setB} onSelect={(r) => (setB(r.symbol), setMarketB(r.market))} placeholder="e.g. PEP" />
            </Field>
            <Field label="History">
              <Segmented options={PERIODS} value={period} onChange={setPeriod} size="sm" />
            </Field>
            <Button type="submit" icon="analyze" loading={loading} disabled={!a.trim() || !b.trim()}>
              Test pair
            </Button>
          </form>
          {error && <p className="mt-3 text-sm text-down">{error}</p>}
        </CardBody>
      </Card>

      {!data ? (
        !error && (
          <Card>
            <EmptyState
              icon="analyze"
              title="Pick two related instruments"
              description="Same-sector stocks (two banks, two oil majors) or two funds on the same index. Cointegrated pairs tend to snap back when their spread stretches."
            />
          </Card>
        )
      ) : (
        <Card>
          <CardHeader
            title={`${data.a} vs ${data.b}`}
            description={`${data.days} shared trading days, ${data.start} to ${data.end}`}
            actions={v && <span className={cx('rounded-md px-2 py-1 text-xs font-medium', v.className)}>{v.title}</span>}
          />
          <CardBody className="space-y-5">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {[
                ['ADF statistic', num(data.adf_stat), data.significance ? `significant at ${data.significance}` : `needs < ${num(data.critical['10%'])}`],
                ['Spread now', `${data.z_now > 0 ? '+' : ''}${num(data.z_now)} σ`, side ?? 'within normal range'],
                ['Half-life', data.half_life_days != null ? `${num(data.half_life_days, 1)} days` : '—', 'time to close half the gap'],
                ['Hedge ratio', num(data.hedge_ratio, 3), `1% in ${data.b} ≈ ${num(data.hedge_ratio, 2)}% in ${data.a}`],
                ['Return correlation', num(data.correlation), 'daily moves'],
                ['ADF lags', String(data.adf_lag), 'chosen by BIC'],
              ].map(([label, value, sub]) => (
                <div key={label}>
                  <div className="text-xs text-faint">{label}</div>
                  <div className="tabular text-base font-semibold">{value}</div>
                  <div className="text-xs text-muted">{sub}</div>
                </div>
              ))}
            </div>

            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.spread} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--color-line)" vertical={false} />
                  <XAxis dataKey="time" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={50}
                    tickFormatter={(t: string) => new Date(t).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })} />
                  <YAxis width={36} domain={['auto', 'auto']} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false}
                    tickFormatter={(v: number) => `${num(v, 0)}σ`} />
                  <Tooltip
                    contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                    formatter={(val) => [`${num(Number(val))} σ`, 'Spread']}
                  />
                  <ReferenceLine y={0} stroke="var(--color-line-strong)" />
                  <ReferenceLine y={2} stroke="var(--color-warn)" strokeDasharray="4 3" />
                  <ReferenceLine y={-2} stroke="var(--color-warn)" strokeDasharray="4 3" />
                  <Line dataKey="z" stroke="var(--color-accent)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="text-xs text-faint">
              Spread = log({data.a}) − {num(data.hedge_ratio, 3)} × log({data.b}), in standard deviations from its mean. Dashed lines at ±2σ.
              {data.verdict === 'not_cointegrated'
                ? ' The spread has not reliably returned to its mean over this window, so a stretched spread is not a signal here.'
                : ' Past behaviour only; relationships break (mergers, regulation, one company stumbling). Not investment advice.'}
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  )
}
