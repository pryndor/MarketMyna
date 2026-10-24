import { useContext, useState } from 'react'
import { Link } from 'react-router-dom'
import { analyzeLink, getHotStocks, type HotBoard } from '../api/listings'
import { cx } from '../lib/cx'
import { pct, price, relativeTime, trendClass } from '../lib/format'
import { InsightActive, liveEvery, useInsight } from '../lib/insight'
import { useLiveQuotes } from '../lib/liveQuotes'
import type { Section } from '../lib/section'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'
import { Button, ScrollBox } from './ui'

const BOARD_KEY = 'marketmyna.hot.board'
const EMPTY: HotBoard['rows'] = []

const COPY: Record<Section, { title: string; loading: string[] }> = {
  trader: {
    title: 'Hot for trading',
    loading: ['Ranking today’s biggest moves…', 'Measuring trading activity…', 'Checking 52-week highs and lows…'],
  },
  investor: {
    title: 'Trending for investors',
    loading: [
      'Reading fundamentals for the largest stocks…',
      'Comparing valuations within each sector…',
      'Matching quality with where price sits in its range…',
      'Checking what mutual funds added…',
    ],
  },
}

function readBoard(area: Section): string | null {
  try {
    return localStorage.getItem(`${BOARD_KEY}.${area}`)
  } catch {
    return null
  }
}

/** Hot stocks for the login area: today's tradeable moves for traders,
 * businesses being re-priced (with fundamentals behind them) for investors. */
export default function HotStocks({ market, area }: { market: string; area: Section }) {
  const [board, setBoard] = useState<string | null>(() => readBoard(area))
  // Trader boards are re-ranked on live prices; investor boards keep their
  // picks (fundamentals) but show live prices.
  const { data, error, at, reload } = useInsight(
    (signal) => getHotStocks(market, area, signal),
    [market, area],
    liveEvery(area === 'trader' ? 15_000 : 30_000),
  )

  function pick(key: string) {
    setBoard(key)
    try {
      localStorage.setItem(`${BOARD_KEY}.${area}`, key)
    } catch {
      /* private mode */
    }
  }

  const copy = COPY[area]
  const active: HotBoard | undefined = data?.boards.find((b) => b.key === board) ?? data?.boards[0]
  // Picks come from the server; prices on screen tick every second from the
  // same feed as the listings table.
  const onScreen = useContext(InsightActive)
  const ticking = useLiveQuotes(active?.rows ?? EMPTY, onScreen)

  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{copy.title}</h2>
          {data && (
            <p className="text-xs text-muted">
              {data.universe}
              {area === 'investor' && data.as_of ? ` · fundamentals ${relativeTime(data.as_of)}` : ''}
              {area === 'trader' && !data.live?.live && data.as_of ? ` · prices ${relativeTime(data.as_of)}` : ''} · facts, not advice
            </p>
          )}
          {data && <InsightLive live={data.live} at={at} ticking={ticking.status.updated} />}
        </div>
        {area === 'trader' && data && (
          <Button variant="ghost" size="sm" icon="refresh" onClick={reload}>
            Refresh
          </Button>
        )}
      </div>

      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={copy.loading} />}
        {data && active && (
          <>
            <div className="flex flex-wrap gap-1.5" role="tablist">
              {data.boards.map((b) => (
                <button
                  key={b.key}
                  type="button"
                  role="tab"
                  aria-selected={b.key === active.key}
                  onClick={() => pick(b.key)}
                  className={cx(
                    'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors',
                    b.key === active.key
                      ? area === 'investor'
                        ? 'border-up/40 bg-up-soft text-up'
                        : 'border-accent/40 bg-accent-soft text-accent-fg'
                      : 'border-line text-muted hover:border-faint hover:text-fg',
                  )}
                >
                  {b.title}
                  <span className={cx('tabular rounded px-1 text-[11px]', b.rows.length ? 'bg-canvas' : 'text-faint')}>{b.rows.length}</span>
                </button>
              ))}
            </div>
            <p className="text-xs text-faint">{active.description}</p>
            <BoardTable board={active} rows={ticking.rows} flash={ticking.flash} />
          </>
        )}
      </div>
    </div>
  )
}

function BoardTable({ board, rows, flash }: { board: HotBoard; rows: HotBoard['rows']; flash: (r: HotBoard['rows'][number]) => string }) {
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-muted">{board.note ?? 'Nothing on this board right now.'}</p>
  }
  return (
    <ScrollBox className="pe-1">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td className="w-full max-w-0 py-2 pe-3">
                <div className="flex items-baseline gap-2">
                  <Link to={analyzeLink(r)} className="font-mono text-sm hover:text-accent-fg">
                    {r.symbol}
                  </Link>
                  <span className="truncate text-[12px] text-faint">{r.name}</span>
                </div>
                <div className="truncate text-xs text-muted">{r.why}</div>
              </td>
              <td className="tabular hidden whitespace-nowrap py-2 pe-3 text-end text-xs text-faint md:table-cell">{r.sector}</td>
              <td className={cx('tabular whitespace-nowrap py-2 pe-3 text-end', flash(r))}>{price(r.price, r.currency)}</td>
              <td className={cx('tabular py-2 text-end', trendClass(r.change_percent))}>{pct(r.change_percent)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollBox>
  )
}
