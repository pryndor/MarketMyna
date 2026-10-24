import { useEffect, useState, type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  getFinancials,
  getFinancialsAiSummary,
  type FinancialPeriod,
  type Financials,
  type FindingTone,
  type QualityScores,
  type Statement,
  type Verdict,
} from '../api/stocks'
import { cx } from '../lib/cx'
import { compact, errorMessage, num } from '../lib/format'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Segmented, Skeleton } from './ui'

type StatementKey = 'income' | 'balance' | 'cashflow'

const STATEMENTS: Array<{ key: StatementKey; title: string; hint: string }> = [
  { key: 'income', title: 'Income statement', hint: 'Revenue, costs and profit over the period' },
  { key: 'balance', title: 'Balance sheet', hint: 'What the company owns and owes at period end' },
  { key: 'cashflow', title: 'Cash flow', hint: 'Cash actually generated and where it went' },
]

type MetricKind = 'pct' | 'x' | 'money' | 'num'

const METRICS: Record<StatementKey, Array<{ key: string; label: string; kind: MetricKind; hint: string }>> = {
  income: [
    { key: 'revenue_growth', label: 'Revenue growth', kind: 'pct', hint: 'Latest period vs the comparable one' },
    { key: 'revenue_cagr', label: 'Revenue CAGR', kind: 'pct', hint: 'Compound annual growth across the periods shown' },
    { key: 'eps_growth', label: 'EPS growth', kind: 'pct', hint: 'Diluted earnings per share, latest vs comparable period' },
    { key: 'gross_margin', label: 'Gross margin', kind: 'pct', hint: 'Revenue left after direct costs' },
    { key: 'operating_margin', label: 'Operating margin', kind: 'pct', hint: 'Profit from the core business per unit of revenue' },
    { key: 'net_margin', label: 'Net margin', kind: 'pct', hint: 'Bottom-line profit per unit of revenue' },
    { key: 'interest_coverage', label: 'Interest coverage', kind: 'x', hint: 'Operating profit / interest expense' },
    { key: 'effective_tax_rate', label: 'Effective tax rate', kind: 'pct', hint: 'Tax / pre-tax income' },
  ],
  balance: [
    { key: 'current_ratio', label: 'Current ratio', kind: 'x', hint: 'Current assets / current liabilities' },
    { key: 'quick_ratio', label: 'Quick ratio', kind: 'x', hint: 'Current assets excluding inventory / current liabilities' },
    { key: 'debt_to_equity', label: 'Debt / equity', kind: 'x', hint: 'Total debt / shareholders equity' },
    { key: 'net_debt', label: 'Net debt', kind: 'money', hint: 'Debt minus cash (negative = net cash)' },
    { key: 'working_capital', label: 'Working capital', kind: 'money', hint: 'Current assets minus current liabilities' },
    { key: 'roe', label: 'Return on equity', kind: 'pct', hint: 'Net income / average equity' },
    { key: 'roa', label: 'Return on assets', kind: 'pct', hint: 'Net income / total assets' },
    { key: 'book_value_per_share', label: 'Book value / share', kind: 'num', hint: 'Equity / shares outstanding' },
    { key: 'goodwill_to_assets', label: 'Goodwill / assets', kind: 'pct', hint: 'Share of assets that are acquisition goodwill & intangibles' },
  ],
  cashflow: [
    { key: 'free_cf', label: 'Free cash flow', kind: 'money', hint: 'Operating cash flow minus capex' },
    { key: 'fcf_margin', label: 'FCF margin', kind: 'pct', hint: 'Free cash flow / revenue' },
    { key: 'cash_conversion', label: 'Cash conversion', kind: 'x', hint: 'Operating cash flow / net income (above 1 is healthy)' },
    { key: 'capex_to_revenue', label: 'Capex / revenue', kind: 'pct', hint: 'Reinvestment intensity' },
    { key: 'shareholder_returns', label: 'Dividends + buybacks', kind: 'money', hint: 'Cash returned to shareholders' },
    { key: 'fcf_payout', label: 'Payout of FCF', kind: 'pct', hint: 'Dividends + buybacks / free cash flow' },
    { key: 'sbc_to_revenue', label: 'Stock comp / revenue', kind: 'pct', hint: 'Stock-based compensation as a share of revenue' },
  ],
}

const CHART_SERIES: Record<StatementKey, Array<{ key: string; color: string }>> = {
  income: [
    { key: 'revenue', color: 'var(--color-accent)' },
    { key: 'operating_income', color: 'var(--color-warn)' },
    { key: 'net_income', color: 'var(--color-up)' },
  ],
  balance: [
    { key: 'total_assets', color: 'var(--color-accent)' },
    { key: 'total_liabilities', color: 'var(--color-down)' },
    { key: 'equity', color: 'var(--color-up)' },
  ],
  cashflow: [
    { key: 'operating_cf', color: 'var(--color-accent)' },
    { key: 'capex', color: 'var(--color-down)' },
    { key: 'free_cf', color: 'var(--color-up)' },
  ],
}

const VERDICT_TONE = { strong: 'up', mixed: 'warn', weak: 'down', 'n/a': 'neutral' } as const
const FINDING_DOT: Record<FindingTone, string> = {
  good: 'bg-up',
  bad: 'bg-down',
  neutral: 'bg-warn',
  info: 'bg-faint',
}

function fmtMetric(value: unknown, kind: MetricKind): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (kind === 'pct') return `${num(value, 1)}%`
  if (kind === 'x') return `${num(value, 2)}x`
  if (kind === 'money') return compact(value)
  return num(value, 2)
}

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <Badge tone={VERDICT_TONE[verdict.label]}>
      {verdict.label}
      {verdict.score != null && <span className="font-normal opacity-80">{verdict.score}</span>}
    </Badge>
  )
}

/** Tiny renderer for the AI summary: ### headings, - bullets, **bold**. */
export function MiniMarkdown({ text }: { text: string }) {
  const inline = (line: string): ReactNode[] =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
    )
  return (
    <div className="space-y-2 text-sm leading-relaxed text-fg/90">
      {text.split('\n').map((raw, i) => {
        const line = raw.trim()
        if (!line) return null
        const heading = line.match(/^#{1,4}\s+(.*)$/)
        if (heading) return <h3 key={i} className="pt-2 text-xs font-semibold tracking-wide text-muted uppercase">{inline(heading[1])}</h3>
        if (/^[-*]\s+/.test(line))
          return (
            <p key={i} className="flex gap-2 ps-1">
              <span className="text-faint">•</span>
              <span>{inline(line.replace(/^[-*]\s+/, ''))}</span>
            </p>
          )
        return <p key={i}>{inline(line)}</p>
      })}
    </div>
  )
}

function StatementChart({ statement, periods, series }: { statement: Statement; periods: string[]; series: typeof CHART_SERIES.income }) {
  const rows = series
    .map((s) => ({ ...s, row: statement.rows.find((r) => r.key === s.key) }))
    .filter((s): s is typeof s & { row: NonNullable<typeof s.row> } => s.row != null)
  if (!rows.length) return null
  const data = periods
    .map((p, i) => ({ period: p, ...Object.fromEntries(rows.map((s) => [s.row.label, s.row.values[i]])) }))
    .filter((d) => rows.some((s) => (d as Record<string, unknown>)[s.row.label] != null))
    .reverse()
  if (data.length < 2) return null
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--color-line)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis
            tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(v: number) => compact(v)}
          />
          <Tooltip
            cursor={{ fill: 'var(--color-raised)' }}
            contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: 'var(--color-muted)' }}
            formatter={(v) => compact(typeof v === 'number' ? v : Number(v))}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} itemSorter={null} />
          {rows.map((s) => (
            <Bar key={s.key} dataKey={s.row.label} fill={s.color} radius={[3, 3, 0, 0]} maxBarSize={28} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function StatementPanel({ data, which }: { data: Financials; which: StatementKey }) {
  const st = data[which]
  const metrics = METRICS[which].filter((m) => typeof st.metrics[m.key] === 'number')
  // Yahoo pads statements with near-empty periods (e.g. one stray row);
  // show only the columns where this statement reports at least 30% of rows.
  const cols = data.periods
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => st.rows.filter((r) => r.values[i] != null).length >= Math.max(1, st.rows.length * 0.3))
  const compare = which === 'income' && typeof st.metrics.compare_label === 'string' ? st.metrics.compare_label : null

  if (!st.rows.length) {
    return <p className="text-xs text-faint">Not available: no {which === 'cashflow' ? 'cash flow' : which} data published for this period.</p>
  }
  return (
    <div className="space-y-5">
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {metrics.map((m) => (
            <div key={m.key} className="rounded-md bg-canvas px-3 py-2" title={m.hint}>
              <div className="text-[12px] text-faint">{m.label}</div>
              <div className="tabular text-sm font-medium">{fmtMetric(st.metrics[m.key], m.kind)}</div>
            </div>
          ))}
        </div>
      )}
      {compare && <p className="-mt-3 text-[12px] text-faint">Growth compares the latest period with the {compare}.</p>}

      {st.findings.length > 0 && (
        <ul className="space-y-1.5">
          {st.findings.map((f, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm">
              <span className={cx('mt-1.5 h-2 w-2 shrink-0 rounded-full', FINDING_DOT[f.tone])} />
              <span className={cx(f.tone === 'info' && 'text-muted')}>{f.text}</span>
            </li>
          ))}
        </ul>
      )}

      <StatementChart statement={st} periods={data.periods} series={CHART_SERIES[which]} />

      <div className="-mx-5 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-y border-line text-[12px] text-faint">
              <th className="sticky start-0 bg-surface px-5 py-2 text-start font-medium">{data.currency ?? ''}</th>
              {cols.map(({ p }) => (
                <th key={p} className="px-3 py-2 text-end font-medium whitespace-nowrap">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {st.rows.map((r) => (
              <tr key={r.key}>
                <td className="sticky start-0 bg-surface px-5 py-1.5 whitespace-nowrap text-muted">{r.label}</td>
                {cols.map(({ i }) => {
                  const v = r.values[i]
                  return (
                    <td key={i} className={cx('tabular px-3 py-1.5 text-end whitespace-nowrap', v != null && v < 0 && 'text-down')}>
                      {r.kind === 'money' ? compact(v) : num(v, r.key === 'eps' ? 2 : 0)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Income statement, balance sheet and cash flow for one company, each
 * with ratios, findings and a verdict, plus an optional AI write-up. */
export default function FinancialStatements({ symbol, market }: { symbol: string; market: string }) {
  const [period, setPeriod] = useState<FinancialPeriod>('annual')
  const [tab, setTab] = useState<StatementKey>('income')
  const [data, setData] = useState<Financials | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ai, setAi] = useState<{ text?: string; error?: string; loading?: boolean }>({})

  useEffect(() => {
    if (market === 'crypto') return
    let cancelled = false
    setData(null)
    setError(null)
    setAi({})
    getFinancials(symbol, market, period)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market, period])

  const runAi = () => {
    setAi({ loading: true })
    getFinancialsAiSummary(symbol, market, period)
      .then((text) => setAi({ text }))
      .catch((err) => setAi({ error: errorMessage(err) }))
  }

  if (market === 'crypto') return null

  return (
    <Card id="section-financials" section="Financial statements">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Financial statements {data && <VerdictBadge verdict={data.overall} />}
          </span>
        }
        description={
          data
            ? [`${data.period} filings`, data.currency, data.sector, `source ${data.source}`].filter(Boolean).join(' · ')
            : 'Income statement, balance sheet and cash flow'
        }
      />
      <CardBody className="space-y-6">
        <Segmented
          size="sm"
          value={period}
          onChange={(v) => setPeriod(v as FinancialPeriod)}
          options={[
            { value: 'annual', label: 'Annual' },
            { value: 'quarterly', label: 'Quarterly' },
          ]}
        />
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !data ? (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        ) : (
          <>
            {/* ---------------------------------------------- summary */}
            <div className="space-y-4">
              <p className="text-sm leading-relaxed">{data.summary}</p>
              <div className="grid gap-2 sm:grid-cols-3">
                {STATEMENTS.map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => setTab(s.key)}
                    title={s.hint}
                    className={cx(
                      'rounded-lg border px-3 py-2.5 text-start transition-colors',
                      tab === s.key ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{s.title}</span>
                      <VerdictBadge verdict={data[s.key].verdict} />
                    </div>
                    <div className="mt-1 text-[12px] text-faint">
                      {data[s.key].verdict.good} positive · {data[s.key].verdict.bad} negative
                      {data[s.key].as_of && ` · as of ${data[s.key].as_of}`}
                    </div>
                  </button>
                ))}
              </div>

              {/* ------------------------------------------ AI analyst */}
              {ai.text ? (
                <div className="rounded-lg border border-line bg-canvas p-4">
                  <div className="mb-1 text-xs font-medium text-accent-fg">AI analyst summary</div>
                  <MiniMarkdown text={ai.text} />
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="sm" variant="secondary" icon="cpu" loading={ai.loading} onClick={runAi}>
                    {ai.loading ? 'Writing analysis…' : 'AI analyst summary'}
                  </Button>
                  <span className="text-[12px] text-faint">Uses your configured AI model to read all three statements.</span>
                </div>
              )}
              {ai.error && (
                <Alert title="AI summary failed" onDismiss={() => setAi({})}>
                  {ai.error}
                </Alert>
              )}
            </div>

            {data.quality && <QualityPanel q={data.quality} />}

            {/* ---------------------------------------------- statement */}
            <div className="space-y-4 border-t border-line pt-5">
              <Segmented
                value={tab}
                onChange={(v) => setTab(v as StatementKey)}
                options={STATEMENTS.map((s) => ({ value: s.key, label: s.title, hint: s.hint }))}
                showHint
              />
              <StatementPanel data={data} which={tab} />
            </div>

            <p className="text-[12px] text-faint">
              Rule-based reading of published filings - facts, not advice. Figures as reported by {data.source}; missing rows mean the
              company or data source doesn't publish them.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

const PIOTROSKI_TONE = { strong: 'up', average: 'warn', weak: 'down' } as const
const ZONE_TONE = { safe: 'up', grey: 'warn', distress: 'down' } as const
const ALTMAN_NAMES: Record<string, string> = {
  working_capital: 'Working capital / assets',
  retained_earnings: 'Retained earnings / assets',
  ebit: 'Operating profit / assets',
  market_value_to_liabilities: 'Market value / liabilities',
  book_equity_to_liabilities: 'Book equity / liabilities',
  sales: 'Sales / assets',
}
const BENEISH_NAMES: Record<string, string> = {
  DSRI: 'Receivables vs sales',
  GMI: 'Gross margin slip',
  AQI: 'Soft assets share',
  SGI: 'Sales growth',
  DEPI: 'Depreciation slowdown',
  SGAI: 'Overheads per sale',
  LVGI: 'Leverage change',
  TATA: 'Accruals to assets',
}

function ScoreBox({ title, badge, children }: { title: string; badge: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border border-line px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="whitespace-nowrap text-sm font-medium">{title}</span>
        <span className="shrink-0 whitespace-nowrap">{badge}</span>
      </div>
      <div className="mt-1 space-y-1.5 text-[12px] text-muted">{children}</div>
    </div>
  )
}

/** Piotroski F, Altman Z and Beneish M from the last three annual filings. */
function QualityPanel({ q }: { q: QualityScores }) {
  if (q.note)
    return (
      <div className="border-t border-line pt-5">
        <div className="mb-1 text-sm font-medium">Quality scores</div>
        <p className="text-[12px] text-faint">{q.note}</p>
      </div>
    )
  const { piotroski: p, altman: a, beneish: b } = q
  return (
    <div className="space-y-3 border-t border-line pt-5">
      <div>
        <div className="text-sm font-medium">Quality scores</div>
        <p className="text-[12px] text-faint">Classic accounting checks on the last three annual filings. They describe the filings; they are not a rating.</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {p && (
          <ScoreBox
            title="Piotroski F-score"
            badge={
              <Badge tone={PIOTROSKI_TONE[p.label]}>
                {p.label}
                <span className="font-normal opacity-80">
                  {p.score}/{p.out_of}
                </span>
              </Badge>
            }
          >
            <p>Profitability, balance-sheet and efficiency tests, this year against last. 7-9 strong, 0-3 weak.</p>
            <ul className="space-y-0.5">
              {p.tests.map((t) => (
                <li key={t.key} className="flex items-start gap-1.5">
                  <span className={cx('mt-0.5 shrink-0 font-semibold', t.pass === true ? 'text-up' : t.pass === false ? 'text-down' : 'text-faint')}>
                    {t.pass === true ? '✓' : t.pass === false ? '✗' : '–'}
                  </span>
                  <span className="min-w-0">
                    {t.label} <span className="tabular text-faint">({t.detail})</span>
                  </span>
                </li>
              ))}
            </ul>
          </ScoreBox>
        )}
        {a && (
          <ScoreBox
            title="Altman Z-score"
            badge={
              <Badge tone={ZONE_TONE[a.zone]}>
                {a.zone}
                <span className="font-normal opacity-80">{num(a.score, 2)}</span>
              </Badge>
            }
          >
            <p>
              Financial-distress model, {a.model}. Above {a.safe_above} safe zone, below {a.distress_below} distress zone, in between grey.
            </p>
            <ul className="tabular space-y-0.5 text-faint">
              {Object.entries(a.parts).map(([k, v]) => (
                <li key={k} className="flex justify-between gap-2">
                  <span>{ALTMAN_NAMES[k] ?? k}</span>
                  <span>{v != null ? num(v, 3) : '—'}</span>
                </li>
              ))}
            </ul>
          </ScoreBox>
        )}
        {b && (
          <ScoreBox
            title="Beneish M-score"
            badge={
              <Badge tone={b.flag ? 'down' : 'up'}>
                {b.flag ? 'flag' : 'no flag'}
                <span className="font-normal opacity-80">{num(b.score, 2)}</span>
              </Badge>
            }
          >
            <p>
              Earnings-quality model: above {b.threshold} the filings look like those of companies later found to have overstated profits. A
              flag is a reason to read the notes, not proof.
            </p>
            <ul className="tabular space-y-0.5 text-faint">
              {Object.entries(b.ratios).map(([k, v]) => (
                <li key={k} className="flex justify-between gap-2">
                  <span>
                    {BENEISH_NAMES[k] ?? k} <span className="opacity-70">{k}</span>
                  </span>
                  <span>{v != null ? num(v, 3) : 'n/a (taken as 1)'}</span>
                </li>
              ))}
            </ul>
          </ScoreBox>
        )}
      </div>
    </div>
  )
}
