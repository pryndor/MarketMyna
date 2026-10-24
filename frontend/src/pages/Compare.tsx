import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { compareStocks, getEtfOverlap, type CompareMetric, type CompareResult, type EtfOverlap } from '../api/compare'
import ExportMenu from '../components/ExportMenu'
import SymbolSearch from '../components/SymbolSearch'
import type { ExportTable } from '../lib/exporter'
import { Alert, Card, CardBody, CardHeader, EmptyState, Icon, PageHeader, Segmented, Skeleton } from '../components/ui'
import { cx } from '../lib/cx'
import { compact, errorMessage, num, pct, trendClass } from '../lib/format'
import { labelFor, MARKETS } from '../lib/options'

const COLORS = ['#6d8cff', '#34d399', '#fbbf24', '#f472b6', '#22d3ee']
const PERIODS = [
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
  { value: '3y', label: '3Y' },
  { value: '5y', label: '5Y' },
]
const MAX = 5

type Pick = { symbol: string; market: string }

function parsePicks(raw: string | null): Pick[] {
  if (!raw) return []
  return raw
    .split(',')
    .map((p) => {
      const [symbol, market] = p.split(':')
      return { symbol: (symbol ?? '').trim().toUpperCase(), market: (market || 'us').trim().toLowerCase() }
    })
    .filter((p) => p.symbol)
    .slice(0, MAX)
}

function fmtMetric(m: CompareMetric, v: number | null, currency: string | null): string {
  if (v == null) return '—'
  if (m.kind === 'pct') return `${num(v, 1)}%`
  if (m.kind === 'money') return `${currency ? `${currency} ` : ''}${compact(v)}`
  if (m.kind === 'count') return num(v, 0)
  return num(v, 2)
}

export default function ComparePage() {
  const [params, setParams] = useSearchParams()
  const picks = useMemo(() => parsePicks(params.get('s')), [params])
  const period = params.get('period') ?? '1y'
  const [text, setText] = useState('')
  const [data, setData] = useState<CompareResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function update(next: Pick[], nextPeriod = period) {
    const p: Record<string, string> = {}
    if (next.length) p.s = next.map((x) => `${x.symbol}:${x.market}`).join(',')
    if (nextPeriod !== '1y') p.period = nextPeriod
    setParams(p, { replace: true })
  }

  useEffect(() => {
    if (picks.length < 2) {
      setData(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    compareStocks(picks, period)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && (setError(errorMessage(err)), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [picks, period])

  const colorOf = (sym: string) => COLORS[Math.max(0, picks.findIndex((p) => p.symbol === sym)) % COLORS.length]
  const items = data?.items ?? []
  const currencyOf = (sym: string) => items.find((i) => i.symbol === sym)?.currency ?? null

  return (
    <div>
      <PageHeader
        title="Compare"
        description="Put up to five stocks, ETFs or coins side by side: performance, risk and fundamentals."
        actions={data && <ExportMenu title={`Compare ${items.map((i) => i.symbol).join(' vs ')}`} subtitle={`Period ${period}`} tables={() => exportCompare(data)} />}
      />

      <Card className="mb-6">
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {picks.map((p, i) => (
              <span key={`${p.symbol}:${p.market}`} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-canvas py-1 pe-1 ps-3 text-sm">
                <span className="h-2 w-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="font-mono font-medium">{p.symbol}</span>
                <span className="text-xs text-faint">{labelFor(MARKETS, p.market)}</span>
                <button
                  type="button"
                  className="rounded-full p-1 text-muted hover:bg-raised hover:text-fg"
                  aria-label={`Remove ${p.symbol}`}
                  onClick={() => update(picks.filter((x) => x !== p))}
                >
                  <Icon name="x" className="h-3.5 w-3.5" />
                </button>
              </span>
            ))}
            {picks.length === 0 && <span className="text-sm text-muted">Add at least two symbols.</span>}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {picks.length < MAX && (
              <div className="min-w-0 basis-full sm:max-w-sm sm:flex-1 sm:basis-auto">
                <SymbolSearch
                  value={text}
                  onChange={setText}
                  placeholder={`Add a symbol (${picks.length}/${MAX})`}
                  exclude={picks.map((p) => p.symbol)}
                  onSelect={(row) => {
                    setText('')
                    if (!picks.some((p) => p.symbol === row.symbol.toUpperCase() && p.market === row.market))
                      update([...picks, { symbol: row.symbol.toUpperCase(), market: row.market }])
                  }}
                />
              </div>
            )}
            <Segmented options={PERIODS} value={period} onChange={(v) => update(picks, v)} size="sm" />
          </div>
        </CardBody>
      </Card>

      {picks.length < 2 ? (
        <Card>
          <EmptyState
            icon="compare"
            title="Pick two to five instruments"
            description="Mix markets if you like (say HDFCBANK vs ICICIBANK, or AAPL vs MSFT vs NVDA). Tip: open a stock in Analyze and use its Peers card to fill this in."
          />
        </Card>
      ) : error ? (
        <Alert tone="down">{error}</Alert>
      ) : !data ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className={cx('space-y-6 transition-opacity', loading && 'opacity-60')}>
          {data.warnings.length > 0 && (
            <div className="space-y-1">
              {data.warnings.map((w) => (
                <p key={w} className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">{w}</p>
              ))}
            </div>
          )}

          <Card>
            <CardHeader title="Performance" description="Growth of 100 invested at the start of the period (dividends included)" icon="analyze" />
            <CardBody>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--color-line)" vertical={false} />
                    <XAxis dataKey="time" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={50}
                      tickFormatter={(t: string) => new Date(t).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })} />
                    <YAxis width={40} domain={['auto', 'auto']} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                      labelFormatter={(t) => new Date(String(t)).toLocaleDateString()}
                      formatter={(v, name) => [num(Number(v), 1), name]}
                    />
                    <ReferenceLine y={100} stroke="var(--color-line-strong)" />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {items.map((i) => (
                      <Line key={i.symbol} dataKey={i.symbol} stroke={colorOf(i.symbol)} strokeWidth={1.75} dot={false} connectNulls isAnimationActive={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Returns & risk" description="Total return per window; risk over the selected period" />
            <div className="overflow-x-auto">
              <Table
                items={items}
                colorOf={colorOf}
                rows={[
                  ...data.returns.map((r) => ({
                    label: `${r.window} return`,
                    values: r.values,
                    fmt: (v: number | null) => <span className={trendClass(v)}>{pct(v, 1)}</span>,
                    best: bestOf(r.values, true),
                  })),
                  {
                    label: 'Volatility (annual)',
                    values: pick(data.risk, 'volatility'),
                    fmt: (v: number | null) => (v == null ? '—' : `${num(v, 1)}%`),
                    best: bestOf(pick(data.risk, 'volatility'), false),
                  },
                  {
                    label: 'Max drawdown',
                    values: pick(data.risk, 'max_drawdown'),
                    fmt: (v: number | null) => <span className="text-down">{v == null ? '—' : `${num(v, 1)}%`}</span>,
                    best: bestOf(pick(data.risk, 'max_drawdown'), true),
                  },
                  {
                    label: 'Return per unit of risk',
                    values: pick(data.risk, 'sharpe_like'),
                    fmt: (v: number | null) => num(v, 2),
                    best: bestOf(pick(data.risk, 'sharpe_like'), true),
                  },
                  {
                    label: 'Beta vs home index',
                    values: pick(data.risk, 'beta'),
                    fmt: (v: number | null, sym?: string) => (
                      <span title={sym ? `vs ${data.risk[sym]?.benchmark}` : undefined}>{num(v, 2)}</span>
                    ),
                    best: null,
                  },
                ]}
              />
            </div>
          </Card>

          {data.metrics.length > 0 && (
            <Card>
              <CardHeader title="Fundamentals" description="Highlighted = best in the row. Latest reported figures." />
              <div className="overflow-x-auto">
                <Table
                  items={items}
                  colorOf={colorOf}
                  rows={data.metrics.map((m, idx) => ({
                    label: m.label,
                    section: idx === 0 || data.metrics[idx - 1].group !== m.group ? m.group : undefined,
                    values: m.values,
                    fmt: (v: number | null, sym?: string) => fmtMetric(m, v, sym ? currencyOf(sym) : null),
                    best: m.best,
                  }))}
                />
              </div>
            </Card>
          )}

          {data.correlation && data.correlation.symbols.length > 1 && (
            <Card>
              <CardHeader title="How they move together" description="Correlation of daily returns over the period. Near 1 = move as one; near 0 = independent." />
              <CardBody className="overflow-x-auto">
                <table className="tabular text-sm">
                  <thead>
                    <tr>
                      <th />
                      {data.correlation.symbols.map((s) => (
                        <th key={s} className="px-3 py-1.5 text-end font-mono text-xs font-medium text-muted">{s}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.correlation.matrix.map((row, i) => (
                      <tr key={i}>
                        <th className="py-1.5 pe-3 text-start font-mono text-xs font-medium text-muted">{data.correlation!.symbols[i]}</th>
                        {row.map((v, j) => (
                          <td
                            key={j}
                            className="px-3 py-1.5 text-end"
                            style={i === j || v == null ? undefined : { background: `rgba(109, 140, 255, ${Math.max(0, v) * 0.45})` }}
                          >
                            {i === j ? '—' : num(v, 2)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}
          <EtfOverlapCard picks={picks} />
          <p className="text-xs text-faint">Data: market data feed, delayed. Past performance does not predict future returns. Not investment advice.</p>
        </div>
      )}
    </div>
  )
}

function pick<K extends string>(risk: CompareResult['risk'], key: K): Record<string, number | null> {
  return Object.fromEntries(Object.entries(risk).map(([s, r]) => [s, (r as unknown as Record<string, number | null>)[key] ?? null]))
}

function bestOf(values: Record<string, number | null>, higher: boolean): string | null {
  const entries = Object.entries(values).filter(([, v]) => v != null) as Array<[string, number]>
  if (entries.length < 2) return null
  return entries.reduce((a, b) => ((higher ? b[1] > a[1] : b[1] < a[1]) ? b : a))[0]
}

type Row = {
  label: string
  /** Starts a new titled section above this row. */
  section?: string
  values: Record<string, number | null>
  fmt: (v: number | null, sym?: string) => ReactNode
  best: string | null
}

function Table({ items, rows, colorOf }: { items: CompareResult['items']; rows: Row[]; colorOf: (s: string) => string }) {
  return (
    <table className="tabular w-full min-w-[34rem] text-sm">
      <thead>
        <tr className="border-b border-line text-xs text-muted">
          <th className="sticky start-0 bg-surface px-5 py-2 text-start font-medium" />
          {items.map((i) => (
            <th key={i.symbol} className="px-3 py-2 text-end font-medium">
              <Link to={`/analyze?symbol=${encodeURIComponent(i.symbol)}&market=${i.market}`} className="inline-flex items-center gap-1.5 hover:text-fg" title={i.name}>
                <span className="h-2 w-2 rounded-full" style={{ background: colorOf(i.symbol) }} />
                <span className="font-mono">{i.symbol}</span>
              </Link>
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {rows.map((r) => [
          r.section && (
            <tr key={`s-${r.section}`} className="bg-canvas">
              <td colSpan={items.length + 1} className="px-5 py-1.5 text-xs font-medium text-muted">{r.section}</td>
            </tr>
          ),
          <tr key={r.label}>
            <td className="sticky start-0 bg-surface px-5 py-2 text-muted sm:whitespace-nowrap">{r.label}</td>
            {items.map((i) => (
              <td key={i.symbol} className={cx('px-3 py-2 text-end', r.best === i.symbol && 'bg-accent/10 font-semibold')}>
                {r.fmt(r.values[i.symbol] ?? null, i.symbol)}
              </td>
            ))}
          </tr>,
        ])}
      </tbody>
    </table>
  )
}


/** Pairwise holdings overlap, shown only when at least two picks are ETFs with holdings data. */
function EtfOverlapCard({ picks }: { picks: Pick[] }) {
  const [rows, setRows] = useState<EtfOverlap[] | null>(null)
  const key = picks.map((p) => `${p.symbol}:${p.market}`).join(',')

  useEffect(() => {
    let cancelled = false
    setRows(null)
    const pairs: Array<[Pick, Pick]> = []
    for (let i = 0; i < picks.length; i++) for (let j = i + 1; j < picks.length; j++) pairs.push([picks[i], picks[j]])
    Promise.all(pairs.map(([a, b]) => getEtfOverlap(a, b).catch(() => null)))
      .then((res) => !cancelled && setRows(res.filter((r): r is EtfOverlap => !!r && r.available)))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!rows || rows.length === 0) return null
  return (
    <Card>
      <CardHeader title="ETF holdings overlap" description="Share of each fund's weight sitting in the same stocks. High overlap = little extra diversification." />
      <CardBody className="space-y-3">
        {rows.map((r) => (
          <div key={`${r.a}-${r.b}`} className="space-y-1.5">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span><span className="font-mono">{r.a}</span> &amp; <span className="font-mono">{r.b}</span></span>
              <span className="tabular font-semibold">{num((r.overlap ?? 0) * 100, 1)}% overlap · {r.shared_count} shared</span>
            </div>
            <div className="h-2 rounded-full bg-raised">
              <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.min((r.overlap ?? 0) * 100, 100)}%` }} />
            </div>
            {r.shared && r.shared.length > 0 && (
              <p className="text-xs text-muted">
                Biggest shared: {r.shared.slice(0, 6).map((s) => `${s.symbol} (${num(Math.min(s.weight_a, s.weight_b) * 100, 1)}%)`).join(', ')}
              </p>
            )}
            {r.note && <p className="text-xs text-faint">{r.note}</p>}
          </div>
        ))}
      </CardBody>
    </Card>
  )
}


function exportCompare(data: CompareResult): ExportTable[] {
  const syms = data.items.map((i) => i.symbol)
  const symCols = (kind: 'number' | 'pct') => syms.map((s) => ({ key: s, label: s, kind }))
  return [
    {
      title: 'Overview',
      columns: [
        { key: 'symbol', label: 'Symbol' }, { key: 'name', label: 'Name' }, { key: 'market', label: 'Market' },
        { key: 'currency', label: 'Currency' }, { key: 'sector', label: 'Sector' }, { key: 'industry', label: 'Industry' },
        { key: 'price', label: 'Price', kind: 'number' },
      ],
      rows: data.items,
    },
    {
      title: 'Returns',
      columns: [{ key: 'label', label: 'Window' }, ...symCols('pct')],
      rows: data.returns.map((r) => ({ label: `${r.window} return`, ...r.values })),
    },
    {
      title: 'Risk',
      columns: [
        { key: 'symbol', label: 'Symbol' }, { key: 'return_period', label: 'Return over period %', kind: 'pct' },
        { key: 'volatility', label: 'Volatility (annual) %', kind: 'pct' }, { key: 'max_drawdown', label: 'Max drawdown %', kind: 'pct' },
        { key: 'sharpe_like', label: 'Return per unit of risk', kind: 'number' }, { key: 'beta', label: 'Beta', kind: 'number' },
        { key: 'benchmark', label: 'Beta vs' },
      ],
      rows: Object.entries(data.risk).map(([symbol, r]) => ({ symbol, ...r })),
    },
    {
      title: 'Fundamentals',
      columns: [{ key: 'group', label: 'Group' }, { key: 'label', label: 'Metric' }, ...symCols('number'), { key: 'best', label: 'Best' }],
      rows: data.metrics.map((m) => ({
        group: m.group, label: m.kind === 'pct' ? `${m.label} %` : m.label, ...m.values, best: m.best,
        _kind: m.kind === 'money' ? 'money' : m.kind === 'pct' ? 'pct' : 'number',
      })),
      note: 'Latest reported figures. Money values are in each company\'s own currency.',
    },
    ...(data.correlation
      ? [{
          title: 'Correlation of daily returns',
          columns: [{ key: 'symbol', label: '' }, ...data.correlation.symbols.map((s) => ({ key: s, label: s, kind: 'number' as const }))],
          rows: data.correlation.matrix.map((row, i) => ({
            symbol: data.correlation!.symbols[i],
            ...Object.fromEntries(row.map((v, j) => [data.correlation!.symbols[j], v])),
          })),
        }]
      : []),
    {
      title: 'Performance (rebased to 100)',
      columns: [{ key: 'time', label: 'Date', kind: 'date' }, ...symCols('number')],
      rows: data.chart,
      pdf: false,
    },
  ]
}
