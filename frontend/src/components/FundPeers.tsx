import { useEffect, useMemo, useState } from 'react'
import { getFundPeers, type FundPeerRow, type FundPeers as Peers, type FundRank } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num, pct } from '../lib/format'
import InsightLoader from './InsightLoader'
import { Badge, Segmented } from './ui'

type Col = 'r1' | 'r3' | 'r5' | 'volatility' | 'drawdown' | 'sharpe' | 'similarity'

const COLS: Array<{ key: Col; label: string; hint: string; higher: boolean; fmt: (v: number) => string }> = [
  { key: 'r1', label: '1Y', hint: 'Return over the last year', higher: true, fmt: (v) => pct(v, 1) },
  { key: 'r3', label: '3Y', hint: 'Annualised return, last 3 years', higher: true, fmt: (v) => pct(v, 1) },
  { key: 'r5', label: '5Y', hint: 'Annualised return, last 5 years', higher: true, fmt: (v) => pct(v, 1) },
  { key: 'volatility', label: 'Volatility', hint: 'How much the NAV swings in a year (lower = steadier)', higher: false, fmt: (v) => `${num(v, 1)}%` },
  { key: 'drawdown', label: 'Worst fall', hint: 'Biggest peak-to-trough fall in 3 years', higher: true, fmt: (v) => `${num(v, 1)}%` },
  { key: 'sharpe', label: 'Sharpe', hint: 'Return above a 6.5% risk-free rate per unit of volatility', higher: true, fmt: (v) => num(v, 2) },
  { key: 'similarity', label: 'Moves like', hint: 'How closely its daily NAV moves with this fund (1 = identical)', higher: true, fmt: (v) => num(v, 2) },
]

const QUARTILE: Record<number, { label: string; tone: 'up' | 'accent' | 'warn' | 'down' }> = {
  1: { label: 'Top quartile', tone: 'up' },
  2: { label: '2nd quartile', tone: 'accent' },
  3: { label: '3rd quartile', tone: 'warn' },
  4: { label: 'Bottom quartile', tone: 'down' },
}

const SHOW = 10

/** The fund against the other schemes of its SEBI category and plan:
 * where it ranks, which funds it behaves like, and a sortable table. */
export default function FundPeers({ code, onOpen }: { code: string; onOpen?: (code: string, name: string) => void }) {
  const [data, setData] = useState<Peers | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<Col>('r3')
  const [all, setAll] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError(null)
    setAll(false)
    getFundPeers(code, controller.signal)
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [code])

  const col = COLS.find((c) => c.key === sort)!
  const rows = useMemo(() => {
    if (!data) return []
    return [...data.rows].sort((a, b) => {
      const av = a[sort]
      const bv = b[sort]
      if (av == null) return 1
      if (bv == null) return -1
      return col.higher ? bv - av : av - bv
    })
  }, [data, sort, col])

  if (error) return <p className="text-xs text-faint">Competitors unavailable: {error}</p>
  if (!data)
    return (
      <InsightLoader
        className="min-h-40"
        steps={['Finding funds in the same category…', 'Reading each fund’s NAV history…', 'Ranking returns and risk…']}
      />
    )
  if (data.status !== 'ok' || data.rows.length < 2) return <p className="text-xs text-faint">No comparable funds found in this category.</p>

  const selfIndex = rows.findIndex((r) => r.is_self)
  const visible = all ? rows : rows.filter((_, i) => i < SHOW || i === selfIndex)

  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">Competitors</h3>
        <p className="text-xs text-muted">
          {data.count} {data.category} funds ({data.plan} plan), one scheme per fund house
        </p>
      </div>

      {Object.values(data.ranks).some(Boolean) ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {COLS.filter((c) => c.key !== 'similarity').map((c) => (
            <RankTile key={c.key} label={c.label} hint={c.hint} rank={data.ranks[c.key as keyof Peers['ranks']] ?? null} fmt={c.fmt} />
          ))}
        </div>
      ) : (
        <p className="rounded-lg bg-canvas px-3 py-2 text-xs text-muted">
          Too few funds with enough history in this category to rank it; the table below still compares them side by side.
        </p>
      )}

      {data.closest.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Moves most like:</span>
          {data.closest.map((c) => (
            <button
              key={c.code}
              type="button"
              disabled={!onOpen}
              onClick={() => onOpen?.(c.code, c.name)}
              className="rounded-md bg-raised px-2 py-1 text-fg enabled:hover:bg-accent-soft"
              title={`Daily NAV correlation ${num(c.similarity, 2)} over the last year`}
            >
              {shortName(c.name)} <span className="tabular text-faint">{num(c.similarity, 2)}</span>
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted">Sort by</span>
        <Segmented size="sm" value={sort} onChange={(v) => setSort(v as Col)} options={COLS.map((c) => ({ value: c.key, label: c.label }))} />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-start text-[11px] text-faint">
              <th className="py-1.5 pe-2 font-medium">#</th>
              <th className="py-1.5 pe-2 font-medium">Fund</th>
              {COLS.map((c) => (
                <th key={c.key} className={cx('py-1.5 pe-2 text-end font-medium', c.key === sort && 'text-fg')} title={c.hint}>
                  {c.label}
                </th>
              ))}
              {data.rows.some((r) => r.overlap != null) && <th className="py-1.5 text-end font-medium" title="Share of the portfolio held in common">Overlap</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {visible.map((r) => (
              <Row key={r.code} row={r} position={rows.indexOf(r) + 1} sort={sort} overlapCol={data.rows.some((x) => x.overlap != null)} onOpen={onOpen} />
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > SHOW && (
        <button type="button" className="text-xs text-accent-fg hover:underline" onClick={() => setAll((v) => !v)}>
          {all ? `Show top ${SHOW}` : `Show all ${rows.length} funds`}
        </button>
      )}
      <p className="text-[12px] text-faint">
        From each fund's officially published NAV history. 3Y and 5Y are annualised; risk is measured over 3 years. {data.note}
      </p>
    </section>
  )
}

function shortName(name: string): string {
  return name.replace(/\s*-\s*(Direct|Regular)\b.*$/i, '').replace(/\s+Fund$/i, '')
}

function RankTile({ label, hint, rank, fmt }: { label: string; hint: string; rank: FundRank | null; fmt: (v: number) => string }) {
  const q = rank ? QUARTILE[rank.quartile] : null
  return (
    <div className="rounded-lg bg-canvas px-3 py-2" title={hint}>
      <div className="text-xs text-muted">{label}</div>
      {rank && q ? (
        <>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="tabular text-sm font-semibold">
              #{rank.rank}
              <span className="text-xs font-normal text-faint"> of {rank.of}</span>
            </span>
            <Badge tone={q.tone}>{q.label}</Badge>
          </div>
          <div className="tabular text-[11px] text-faint">category median {fmt(rank.median)}</div>
        </>
      ) : (
        <div className="mt-0.5 text-sm text-faint">—</div>
      )}
    </div>
  )
}

function Row({
  row,
  position,
  sort,
  overlapCol,
  onOpen,
}: {
  row: FundPeerRow
  position: number
  sort: Col
  overlapCol: boolean
  onOpen?: (code: string, name: string) => void
}) {
  return (
    <tr className={cx(row.is_self && 'bg-accent-soft/60')}>
      <td className="tabular py-1.5 pe-2 text-xs text-faint">{position}</td>
      <td className="max-w-[16rem] py-1.5 pe-2">
        {row.is_self || !onOpen ? (
          <span className={cx('block truncate', row.is_self && 'font-semibold')} title={row.name}>
            {shortName(row.name)}
            {row.is_self && <span className="ms-1.5 text-[11px] font-normal text-accent-fg">this fund</span>}
          </span>
        ) : (
          <button type="button" className="block max-w-full truncate text-start hover:text-accent-fg" title={row.name} onClick={() => onOpen(row.code, row.name)}>
            {shortName(row.name)}
          </button>
        )}
        {row.r1 == null && row.since && (
          <span className="block text-[11px] text-faint">
            new fund · since {new Date(row.since).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}
          </span>
        )}
      </td>
      {COLS.map((c) => {
        const v = row[c.key]
        const tone =
          v == null ? 'text-faint' : c.key === 'r1' || c.key === 'r3' || c.key === 'r5' ? (v >= 0 ? 'text-up' : 'text-down') : ''
        return (
          <td key={c.key} className={cx('tabular py-1.5 pe-2 text-end', tone, c.key === sort && 'font-semibold')}>
            {v == null ? '—' : c.key === 'similarity' && row.is_self ? '—' : c.fmt(v)}
          </td>
        )
      })}
      {overlapCol && <td className="tabular py-1.5 text-end text-xs">{row.overlap == null ? '—' : `${num(row.overlap, 0)}%`}</td>}
    </tr>
  )
}
