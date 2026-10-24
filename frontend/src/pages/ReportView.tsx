import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { analyzeLink } from '../api/listings'
import { getReport, type SavedReport, type SmartRow } from '../api/scheduler'
import { Alert, Badge, Button, Card, Input, PageHeader, Segmented, Skeleton } from '../components/ui'
import { cx } from '../lib/cx'
import { exportTables } from '../lib/exporter'
import { errorMessage, num, pct, price, serverTime } from '../lib/format'

const CURRENCY: Record<string, string> = { india: 'INR', us: 'USD', china_a: 'CNY', hong_kong: 'HKD', crypto: 'USD' }

/** Readings of the indicators, never a call (src/core/compliance.py). */
const READING_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'positive', label: 'Bullish' },
  { value: 'mixed', label: 'Neutral' },
  { value: 'negative', label: 'Bearish' },
]
const READING_LABELS: Record<string, string> = { positive: '▲ Bullish', mixed: '◆ Neutral', negative: '▼ Bearish' }
const READING_TONES: Record<string, 'up' | 'warn' | 'down'> = { positive: 'up', mixed: 'warn', negative: 'down' }

/** The group a row is counted and filtered in (the server strips calls from old reports). */
function group(r: SmartRow): string {
  return r.reading ?? 'mixed'
}

type SortKey = 'attention' | 'symbol' | 'change_percent' | 'rsi' | 'band'

/** Where price sits in its normal range: 0% = bottom band, 100% = top. */
function bandPosition(r: SmartRow): number | null {
  if (r.price == null || r.normal_low == null || r.normal_high == null || r.normal_high <= r.normal_low) return null
  return ((r.price - r.normal_low) / (r.normal_high - r.normal_low)) * 100
}

function sortValue(r: SmartRow, key: SortKey): number | string {
  switch (key) {
    case 'symbol':
      return r.symbol
    case 'change_percent':
      return r.change_percent ?? -Infinity
    case 'rsi':
      return r.rsi ?? -Infinity
    case 'band':
      return bandPosition(r) ?? -Infinity
    default:
      return r.attention ?? -Infinity
  }
}

const CSV_COLUMNS: Array<keyof SmartRow> = [
  'symbol', 'name', 'market', 'price', 'change_percent', 'reading', 'pe', 'normal_low', 'normal_high',
  'week_low', 'week_high', 'rsi', 'trend', 'ai_summary', 'reasons',
]

/** The full smart report behind a message's link: every monitored stock
 * with its normal range, 1-week range and indicator reading. */
export default function ReportViewPage() {
  const { token = '' } = useParams()
  const [report, setReport] = useState<SavedReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'attention', desc: true })

  useEffect(() => {
    setReport(null)
    setError(null)
    getReport(token)
      .then(setReport)
      .catch((err) => setError(errorMessage(err)))
  }, [token])

  const good = useMemo(() => (report?.rows ?? []).filter((r) => !r.error), [report])
  const failed = useMemo(() => (report?.rows ?? []).filter((r) => r.error), [report])
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    good.forEach((r) => (c[group(r)] = (c[group(r)] ?? 0) + 1))
    return c
  }, [good])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = good.filter(
      (r) =>
        (filter === 'all' || group(r) === filter) &&
        (!q || r.symbol.toLowerCase().includes(q) || (r.name ?? '').toLowerCase().includes(q)),
    )
    return [...list].sort((a, b) => {
      const x = sortValue(a, sort.key)
      const y = sortValue(b, sort.key)
      const cmp = typeof x === 'string' ? x.localeCompare(String(y)) : x - (y as number)
      return sort.desc ? -cmp : cmp
    })
  }, [good, filter, query, sort])

  function download() {
    if (!report) return
    void exportTables('csv', 'marketmyna-report', [
      {
        title: 'Smart report',
        columns: CSV_COLUMNS.map((c) => ({ key: c, label: c })),
        rows: report.rows,
      },
    ])
  }

  if (error) return <Alert title="Report not available">{error}</Alert>
  if (!report) return <Skeleton className="h-96 w-full" />

  const header = (key: SortKey, label: string, align: 'left' | 'right' = 'right') => (
    <th className={cx('px-3 py-2 font-medium whitespace-nowrap', align === 'right' ? 'text-end' : 'text-start')}>
      <button
        type="button"
        className={cx('hover:text-fg', sort.key === key && 'text-fg')}
        onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'symbol' }))}
      >
        {label}
        {sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )

  return (
    <div>
      <PageHeader
        title={report.title}
        description={
          <>
            {report.created_at && serverTime(report.created_at).toLocaleString()} · {good.length} stocks analysed
            {failed.length > 0 && `, ${failed.length} unavailable`}. Computed from market data, not investment advice.
          </>
        }
        actions={
          <Button variant="secondary" size="sm" onClick={download}>
            Download CSV
          </Button>
        }
      />

      <div className="mb-4">
        <Alert tone="accent" title="How to read this report">
          This report describes what the market data shows. It is not a recommendation to buy, sell or hold any
          stock. "Bullish" or "bearish" means most of the indicators we track (trend, momentum,
          where the price sits in its range, valuation) lean that way today; they can change quickly and are often
          wrong. Do your own research or speak to a SEBI-registered adviser before you invest.
        </Alert>
      </div>

      <div className="mb-4 grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line">
        {(['positive', 'mixed', 'negative'] as const).map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => setFilter(filter === a ? 'all' : a)}
            className={cx('bg-surface px-4 py-3 text-start hover:bg-raised', filter === a && 'bg-raised')}
          >
            <div className="text-xs font-medium text-muted capitalize">{READING_LABELS[a]}</div>
            <div
              className={cx(
                'tabular text-lg font-semibold',
                a === 'positive' ? 'text-up' : a === 'negative' ? 'text-down' : '',
              )}
            >
              {counts[a] ?? 0}
            </div>
          </button>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented options={READING_FILTERS} value={filter} onChange={setFilter} size="sm" />
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by symbol or name" className="w-full sm:w-64" />
      </div>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-xs text-muted">
              <tr>
                {header('symbol', 'Stock', 'left')}
                <th className="px-3 py-2 text-start font-medium">Indicators</th>
                {header('change_percent', 'Price')}
                {header('band', 'Normal range')}
                <th className="px-3 py-2 text-end font-medium">P/E</th>
                <th className="px-3 py-2 text-end font-medium whitespace-nowrap">1-week range</th>
                {header('rsi', 'RSI')}
                {header('attention', 'What stands out', 'left')}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((r) => (
                <ReportRow key={`${r.market}:${r.symbol}`} row={r} />
              ))}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-xs text-muted">
                    No stocks match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {failed.length > 0 && (
        <details className="mt-4 rounded-lg border border-line px-3 py-2 text-xs text-muted">
          <summary className="cursor-pointer">{failed.length} stocks could not be analysed</summary>
          <ul className="mt-2 space-y-1">
            {failed.map((r) => (
              <li key={r.symbol}>
                <span className="font-mono text-fg">{r.symbol}</span>: {r.error}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-6 grid gap-3 text-xs text-muted sm:grid-cols-2">
        <p>
          <b className="text-fg">Normal range</b>: the 20-day Bollinger band, where the price usually trades. The bar
          shows where today's price sits in it; above the top is stretched, below the bottom is washed out.
        </p>
        <p>
          <b className="text-fg">1-week range</b>: where about two weeks in three end, from the last 60 days of
          volatility. A range, not a target.
        </p>
        <p>
          <b className="text-fg">Indicators</b>: how most of trend, momentum (RSI), where the price sits in its
          range and valuation lean today. It describes the data; it is not a buy, sell or hold call. Stocks marked{' '}
          <Badge tone="accent">AI</Badge> have an AI summary of their figures.
        </p>
      </div>
    </div>
  )
}

function ReportRow({ row: r }: { row: SmartRow }) {
  const cur = CURRENCY[r.market]
  const band = bandPosition(r)
  const reading = r.reading ?? 'mixed'
  return (
    <tr className="align-top hover:bg-raised/50">
      <td className="px-3 py-2">
        <Link to={analyzeLink(r)} className="font-mono font-medium hover:underline">
          {r.symbol}
        </Link>
        {r.name && <div className="max-w-44 truncate text-xs text-muted">{r.name}</div>}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <Badge tone={READING_TONES[reading]}>{READING_LABELS[reading]}</Badge>
        {r.ai && (
          <span className="ms-1">
            <Badge tone="accent">AI</Badge>
          </span>
        )}
      </td>
      <td className="tabular px-3 py-2 text-end whitespace-nowrap">
        <div>{price(r.price, cur)}</div>
        <div className={cx('text-xs', (r.change_percent ?? 0) >= 0 ? 'text-up' : 'text-down')}>{pct(r.change_percent)}</div>
      </td>
      <td className="tabular px-3 py-2 text-end whitespace-nowrap">
        <div className="text-xs">
          {price(r.normal_low, cur)} – {price(r.normal_high, cur)}
        </div>
        {band != null && (
          <div className="relative mt-1 ms-auto h-1.5 w-24 rounded-full bg-line" title={`${num(band, 0)}% of the range`}>
            <span
              className={cx('absolute top-1/2 h-2.5 w-1 -translate-y-1/2 rounded-full', band > 100 ? 'bg-down' : band < 0 ? 'bg-up' : 'bg-fg')}
              style={{ left: `${Math.max(0, Math.min(100, band))}%` }}
            />
          </div>
        )}
      </td>
      <td className="tabular px-3 py-2 text-end text-xs whitespace-nowrap">{r.pe != null ? num(r.pe, 1) : '—'}</td>
      <td className="tabular px-3 py-2 text-end text-xs whitespace-nowrap">
        {price(r.week_low, cur)} – {price(r.week_high, cur)}
      </td>
      <td className="tabular px-3 py-2 text-end whitespace-nowrap">
        <div className={cx((r.rsi ?? 50) > 70 && 'text-down', (r.rsi ?? 50) < 30 && 'text-up')}>{num(r.rsi, 0)}</div>
        <div className="text-xs text-muted">{r.trend}</div>
      </td>
      <td className="max-w-72 px-3 py-2 text-xs text-muted">
        {r.ai_summary || (r.reasons?.length ? r.reasons.join(', ') : '—')}
      </td>
    </tr>
  )
}
