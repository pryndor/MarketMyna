import { useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  getStrategies,
  runBacktest,
  type BacktestMetrics,
  type BacktestRequest,
  type BacktestResult,
  type StrategyInfo,
} from '../../api/trade'
import { cx } from '../../lib/cx'
import { errorMessage, num, pct, price as fmtPrice } from '../../lib/format'
import { toast } from '../../lib/toast'
import { Alert, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Segmented, Select, Switch } from '../ui'
import { CURRENCY } from './shared'
import StatTile from './StatTile'

const PERIODS = [
  { value: '1y', label: '1 year' },
  { value: '2y', label: '2 years' },
  { value: '5y', label: '5 years' },
  { value: '10y', label: '10 years' },
  { value: 'max', label: 'All history' },
]

const PARAM_LABELS: Record<string, string> = {
  fast: 'Fast average (bars)',
  slow: 'Slow average (bars)',
  entry_days: 'Entry: N-bar high',
  exit_days: 'Exit: M-bar low',
  buy_below: 'Buy when RSI below',
  sell_above: 'Exit when RSI above',
  period: 'Period',
  multiplier: 'ATR multiplier',
  min_score: 'Min model lean (-1 to 1)',
  k: 'Neighbours (k)',
  horizon: 'Model looks ahead (bars)',
  min_vote: 'Min neighbour vote',
  use_filter: 'Use the kNN filter (1 = yes, 0 = no)',
}

export default function BacktestTab({ symbol, market }: { symbol: string; market: string }) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [req, setReq] = useState<BacktestRequest>({
    symbol,
    market,
    interval: '1d',
    period: '5y',
    strategy: 'ema_cross',
    params: {},
    capital: 100000,
    sizing: 'percent',
    position_pct: 100,
    risk_pct: 1,
    stop_type: 'atr',
    stop_value: 2,
    target_r: null,
    cost_pct: market === 'india' ? 0.12 : 0.05,
    slippage_pct: 0.05,
    allow_short: false,
    optimize: false,
    objective: 'sharpe',
  })
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    getStrategies().then(setStrategies).catch(() => setStrategies([]))
  }, [])
  useEffect(() => {
    setReq((r) => ({ ...r, symbol, market }))
    setResult(null)
  }, [symbol, market])

  const strat = strategies.find((s) => s.id === req.strategy)
  const set = (patch: Partial<BacktestRequest>) => setReq((r) => ({ ...r, ...patch }))
  const cur = CURRENCY[market]

  async function run() {
    setRunning(true)
    try {
      const r = await runBacktest(req)
      setResult(r)
      if (req.optimize && r.optimization) set({ params: r.optimization.best })
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  const m = result?.metrics
  const split = result?.split
  const overfit =
    split && split.train.total_return > 0 && (split.test.total_return < 0 || (split.test.sharpe ?? 0) < (split.train.sharpe ?? 0) / 2)

  return (
    <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <Card>
        <CardHeader title="Strategy test" description={`${symbol} · signals on close, filled at the next open`} />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Segmented
              options={[
                { value: '1d', label: 'Daily' },
                { value: '1wk', label: 'Weekly' },
                { value: '1h', label: 'Hourly' },
              ]}
              value={req.interval}
              onChange={(v) => set({ interval: v as BacktestRequest['interval'] })}
              size="sm"
            />
            <Select className="w-36" options={PERIODS} value={req.period} onChange={(e) => set({ period: e.target.value as BacktestRequest['period'] })} />
          </div>
          {req.interval === '1h' && <p className="text-[12px] text-muted">Hourly history is limited to the last 2 years.</p>}

          <Field label="Strategy" hint={strat?.description}>
            <Select
              options={strategies.map((s) => ({ value: s.id, label: s.label }))}
              value={req.strategy}
              onChange={(e) => set({ strategy: e.target.value, params: {} })}
            />
          </Field>
          {strat && (
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(strat.params).map(([k, def]) => (
                <Field key={k} label={PARAM_LABELS[k] ?? k}>
                  <Input
                    type="number"
                    step="any"
                    value={req.params[k] ?? def}
                    onChange={(e) => set({ params: { ...req.params, [k]: parseFloat(e.target.value) } })}
                  />
                </Field>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <Field label={`Capital (${cur})`}>
              <Input type="number" value={req.capital} onChange={(e) => set({ capital: parseFloat(e.target.value) || 0 })} />
            </Field>
            <Field label="Sizing">
              <Select
                options={[
                  { value: 'percent', label: '% of equity' },
                  { value: 'risk', label: 'Risk % at stop' },
                ]}
                value={req.sizing}
                onChange={(e) => set({ sizing: e.target.value as BacktestRequest['sizing'] })}
              />
            </Field>
            {req.sizing === 'percent' ? (
              <Field label="Position % of equity">
                <Input type="number" value={req.position_pct} onChange={(e) => set({ position_pct: parseFloat(e.target.value) || 0 })} />
              </Field>
            ) : (
              <Field label="Risk % per trade">
                <Input type="number" step="0.1" value={req.risk_pct} onChange={(e) => set({ risk_pct: parseFloat(e.target.value) || 0 })} />
              </Field>
            )}
            <Field label="Stop loss">
              <Select
                options={[
                  { value: 'none', label: 'None' },
                  { value: 'percent', label: '% below entry' },
                  { value: 'atr', label: 'ATR multiple' },
                ]}
                value={req.stop_type}
                onChange={(e) => set({ stop_type: e.target.value as BacktestRequest['stop_type'] })}
              />
            </Field>
            {req.stop_type !== 'none' && (
              <>
                <Field label={req.stop_type === 'atr' ? 'ATR ×' : 'Stop %'}>
                  <Input type="number" step="0.1" value={req.stop_value} onChange={(e) => set({ stop_value: parseFloat(e.target.value) || 0 })} />
                </Field>
                <Field label="Target (R, optional)">
                  <Input
                    type="number"
                    step="0.5"
                    value={req.target_r ?? ''}
                    onChange={(e) => set({ target_r: e.target.value ? parseFloat(e.target.value) : null })}
                  />
                </Field>
              </>
            )}
            <Field label="Costs % per side">
              <Input type="number" step="0.01" value={req.cost_pct} onChange={(e) => set({ cost_pct: parseFloat(e.target.value) || 0 })} />
            </Field>
            <Field label="Slippage % per side">
              <Input type="number" step="0.01" value={req.slippage_pct} onChange={(e) => set({ slippage_pct: parseFloat(e.target.value) || 0 })} />
            </Field>
          </div>
          {req.sizing === 'risk' && req.stop_type === 'none' && (
            <p className="text-xs text-warn">Risk sizing needs a stop; without one, % of equity is used.</p>
          )}
          <Switch checked={req.allow_short} onChange={(allow_short) => set({ allow_short })} label="Also trade short" description="Exit signals open a short position." />
          <div className="rounded-lg border border-line p-3">
            <Switch
              checked={req.optimize}
              onChange={(optimize) => set({ optimize })}
              label="Optimise parameters"
              description="Grid-search on the first 70% of history only, then judge the winner on the unseen last 30%."
            />
            {req.optimize && (
              <Field label="Optimise for" className="mt-3">
                <Select
                  options={[
                    { value: 'sharpe', label: 'Sharpe ratio (risk-adjusted)' },
                    { value: 'total_return', label: 'Total return' },
                    { value: 'cagr', label: 'CAGR' },
                    { value: 'profit_factor', label: 'Profit factor' },
                  ]}
                  value={req.objective}
                  onChange={(e) => set({ objective: e.target.value as BacktestRequest['objective'] })}
                />
              </Field>
            )}
          </div>
          <Button onClick={run} loading={running} icon="play" className="w-full">
            {running ? 'Testing…' : 'Run backtest'}
          </Button>
          <p className="text-[12px] text-faint">
            Past results don't predict future ones. Costs default to Indian delivery charges (~0.12% a side); change them for your broker.
          </p>
        </CardBody>
      </Card>

      {!result || !m ? (
        <Card>
          <EmptyState icon="analyze" title="No backtest yet" description="Choose a strategy and run it on this stock's history." />
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
            <StatTile label="Total return" value={pct(m.total_return)} tone={m.total_return >= 0 ? 'up' : 'down'} sub={`buy & hold ${pct(m.buy_hold_return)}`} />
            <StatTile label="CAGR" value={pct(m.cagr)} />
            <StatTile label="Max drawdown" value={pct(m.max_drawdown)} tone="down" />
            <StatTile label="Sharpe" value={num(m.sharpe)} />
            <StatTile label="Trades" value={String(m.trades)} sub={`avg ${num(m.avg_bars, 0)} bars held`} />
            <StatTile label="Win rate" value={m.win_rate != null ? `${m.win_rate}%` : '—'} />
            <StatTile label="Profit factor" value={num(m.profit_factor)} sub={m.avg_r != null ? `avg ${m.avg_r}R` : undefined} />
            <StatTile label="Time in market" value={m.exposure != null ? `${m.exposure}%` : '—'} sub={`final ${fmtPrice(m.final_equity, cur)}`} />
          </div>

          {m.trades < 10 && (
            <Alert tone="warn" title="Few trades">
              {m.trades} trades is too small a sample to trust. Use a longer period or a faster strategy.
            </Alert>
          )}
          {overfit && (
            <Alert tone="warn" title="Looks overfit">
              It did well on the first 70% of history but not on the last 30%. The edge may not be real.
            </Alert>
          )}

          <Card>
            <CardHeader
              title="Equity vs buy & hold"
              description={`${new Date(m.start).toLocaleDateString()} – ${new Date(m.end).toLocaleDateString()} · ${m.bars} bars · params ${Object.entries(result.params).map(([k, v]) => `${k}=${v}`).join(', ')}`}
            />
            <CardBody className="space-y-2">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={result.equity} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--color-line)" vertical={false} />
                    <XAxis dataKey="time" tickFormatter={(t: string) => new Date(t).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={40} />
                    <YAxis orientation="right" width={64} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                    <Tooltip contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }} labelFormatter={(t) => new Date(String(t)).toLocaleDateString()} formatter={(v, n) => [fmtPrice(Number(v), cur), n === 'equity' ? 'Strategy' : 'Buy & hold']} />
                    <Legend formatter={(v) => (v === 'equity' ? 'Strategy' : 'Buy & hold')} wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="equity" stroke="var(--color-accent)" dot={false} strokeWidth={1.75} />
                    <Line type="monotone" dataKey="buy_hold" stroke="var(--color-faint)" dot={false} strokeWidth={1} strokeDasharray="4 3" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="h-24">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={result.equity} margin={{ top: 0, right: 4, bottom: 0, left: 0 }}>
                    <XAxis dataKey="time" hide />
                    <YAxis orientation="right" width={64} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
                    <Tooltip contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }} labelFormatter={(t) => new Date(String(t)).toLocaleDateString()} formatter={(v) => [`${v}%`, 'Drawdown']} />
                    <Area type="monotone" dataKey="drawdown" stroke="var(--color-down)" fill="var(--color-down)" fillOpacity={0.15} strokeWidth={1} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardBody>
          </Card>

          {split && (
            <Card>
              <CardHeader title="Out-of-sample check" description="Same settings on the first 70% of history vs the last 30%." />
              <SplitTable train={split.train} test={split.test} />
            </Card>
          )}

          {result.optimization && (
            <Card>
              <CardHeader
                title="Optimisation"
                description={`Best on the training part by ${result.optimization.objective}: ${Object.entries(result.optimization.best).map(([k, v]) => `${k}=${v}`).join(', ')} · on unseen data: ${pct(result.optimization.test.total_return)} return, Sharpe ${num(result.optimization.test.sharpe)}`}
              />
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 border-y border-line bg-surface text-xs text-muted">
                    <tr>
                      <th className="px-4 py-2 text-start font-medium">Parameters</th>
                      <th className="px-3 py-2 text-end font-medium">Return</th>
                      <th className="px-3 py-2 text-end font-medium">Sharpe</th>
                      <th className="px-4 py-2 text-end font-medium">Trades</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {[...result.optimization.grid]
                      .sort((a, b) => (b.score ?? -1e9) - (a.score ?? -1e9))
                      .map((g) => {
                        const best = JSON.stringify(g.params) === JSON.stringify(result.optimization!.best)
                        return (
                          <tr key={JSON.stringify(g.params)} className={cx(best && 'bg-accent-soft/50')}>
                            <td className="px-4 py-1.5 font-mono text-xs">{Object.entries(g.params).map(([k, v]) => `${k}=${v}`).join(' ')}</td>
                            <td className={cx('tabular px-3 py-1.5 text-end', g.total_return >= 0 ? 'text-up' : 'text-down')}>{pct(g.total_return)}</td>
                            <td className="tabular px-3 py-1.5 text-end">{num(g.sharpe)}</td>
                            <td className="tabular px-4 py-1.5 text-end">{g.trades}</td>
                          </tr>
                        )
                      })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <Card className="overflow-hidden">
            <CardHeader title="Trades" description={`${result.trades.length} total`} />
            <div className="max-h-96 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 border-y border-line bg-surface text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2 text-start font-medium">Entry</th>
                    <th className="px-3 py-2 text-start font-medium">Exit</th>
                    <th className="px-3 py-2 text-end font-medium">Prices</th>
                    <th className="px-3 py-2 text-end font-medium">Return</th>
                    <th className="px-3 py-2 text-end font-medium">P&amp;L</th>
                    <th className="px-4 py-2 text-start font-medium">Exit reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {[...result.trades].reverse().map((t, i) => (
                    <tr key={i}>
                      <td className="px-4 py-1.5 text-xs whitespace-nowrap">
                        <span className={cx('me-1.5 font-medium uppercase', t.side === 'long' ? 'text-up' : 'text-down')}>{t.side}</span>
                        {new Date(t.entry_time).toLocaleDateString()}
                      </td>
                      <td className="px-3 py-1.5 text-xs whitespace-nowrap text-muted">{new Date(t.exit_time).toLocaleDateString()}</td>
                      <td className="tabular px-3 py-1.5 text-end text-xs whitespace-nowrap">
                        {num(t.entry)} → {num(t.exit)}
                      </td>
                      <td className={cx('tabular px-3 py-1.5 text-end', t.return_pct >= 0 ? 'text-up' : 'text-down')}>{pct(t.return_pct)}</td>
                      <td className={cx('tabular px-3 py-1.5 text-end', t.pnl >= 0 ? 'text-up' : 'text-down')}>{fmtPrice(t.pnl, cur)}</td>
                      <td className="px-4 py-1.5 text-xs text-muted">{t.reason}{t.r != null && ` · ${t.r}R`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}

function SplitTable({ train, test }: { train: BacktestMetrics; test: BacktestMetrics }) {
  const rows: Array<[string, (m: BacktestMetrics) => string]> = [
    ['Period', (m) => `${new Date(m.start).toLocaleDateString()} – ${new Date(m.end).toLocaleDateString()}`],
    ['Return', (m) => pct(m.total_return)],
    ['Buy & hold', (m) => pct(m.buy_hold_return)],
    ['Max drawdown', (m) => pct(m.max_drawdown)],
    ['Sharpe', (m) => num(m.sharpe)],
    ['Trades', (m) => String(m.trades)],
    ['Win rate', (m) => (m.win_rate != null ? `${m.win_rate}%` : '—')],
  ]
  return (
    <table className="w-full text-sm">
      <thead className="border-y border-line text-xs text-muted">
        <tr>
          <th className="px-4 py-2 text-start font-medium" />
          <th className="px-3 py-2 text-end font-medium">First 70% (in-sample)</th>
          <th className="px-4 py-2 text-end font-medium">Last 30% (unseen)</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {rows.map(([label, f]) => (
          <tr key={label}>
            <td className="px-4 py-1.5 text-muted">{label}</td>
            <td className="tabular px-3 py-1.5 text-end">{f(train)}</td>
            <td className="tabular px-4 py-1.5 text-end">{f(test)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
