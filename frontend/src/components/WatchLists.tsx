import { useContext, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { analyzeLink, getWatchLists, getWatchNotes, type WatchBoard, type WatchNotes, type WatchPeriod } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num, pct, price, relativeTime, trendClass } from '../lib/format'
import { InsightActive, liveEvery, useInsight } from '../lib/insight'
import { useLiveQuotes } from '../lib/liveQuotes'
import { getAiStatus } from '../api/agent'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'
import { Badge, Button, ScrollBox, Segmented } from './ui'

// "Stocks to watch" (today / this week / this month) and "New stock ideas"
// on the Markets page; server side marketmyna/services/stocks_to_watch.py. The AI
// notes need an AI model (a key in Settings, or LLM_MODEL for a local one).

const PERIOD_KEY = 'marketmyna.watch.period'
const BOARD_KEY = 'marketmyna.watch.board'
const EMPTY: WatchBoard['rows'] = []

const PERIODS = [
  { value: 'day', label: 'Today', hint: 'Moves and breakouts in today’s session' },
  { value: 'week', label: 'This week', hint: 'The last 5 sessions against the usual' },
  { value: 'month', label: 'This month', hint: 'The last 21 sessions: trends turning and extremes' },
]

const LOADING: Record<WatchPeriod, string[]> = {
  day: ['Loading a year of prices for the largest stocks…', 'Comparing today’s volume with the usual…', 'Finding breakouts…'],
  week: ['Loading a year of prices for the largest stocks…', 'Measuring this week against the last 4…', 'Spotting volume building…'],
  month: ['Loading a year of prices for the largest stocks…', 'Checking 50- and 200-day averages…', 'Reading RSI…'],
  ideas: ['Reading fundamentals for the largest stocks…', 'Matching quality with fresh trend turns…', 'Comparing with last week’s ideas…'],
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode */
  }
}

export default function WatchLists({ market, ideas = false }: { market: string; ideas?: boolean }) {
  const [periodPick, setPeriodPick] = useState(() => read(PERIOD_KEY) ?? 'day')
  const period: WatchPeriod = ideas ? 'ideas' : ((['day', 'week', 'month'].includes(periodPick) ? periodPick : 'day') as WatchPeriod)
  const boardKey = `${BOARD_KEY}.${period}`
  const [boardPick, setBoardPick] = useState<Record<string, string | null>>({})
  const board = boardPick[period] ?? read(boardKey)
  const { data, error, at } = useInsight((signal) => getWatchLists(market, period, signal), [market, period], liveEvery(60_000))

  const active = data?.boards.find((b) => b.key === board) ?? data?.boards[0]
  const onScreen = useContext(InsightActive)
  const ticking = useLiveQuotes(active?.rows ?? EMPTY, onScreen)

  function pickPeriod(p: string) {
    write(PERIOD_KEY, p)
    setPeriodPick(p)
  }

  function pickBoard(key: string) {
    write(boardKey, key)
    setBoardPick((b) => ({ ...b, [period]: key }))
  }

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{ideas ? 'New stock ideas' : 'Stocks to watch'}</h2>
          <p className="text-xs text-muted">
            {ideas
              ? 'Sound businesses whose price trend just turned, from the largest stocks; marked New when they were not on the list a week ago'
              : 'What stands out today, this week and this month among the largest stocks, with the levels to watch'}
            {data && ` · ${data.universe} · facts, not advice`}
          </p>
          {data && <InsightLive live={data.live} at={at} ticking={ticking.status.updated} />}
        </div>
        {!ideas && <Segmented size="sm" options={PERIODS} value={period} onChange={pickPeriod} showHint />}
      </div>

      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={LOADING[period]} />}
        {data && active && (
          <>
            <div className="flex flex-wrap gap-1.5" role="tablist">
              {data.boards.map((b) => (
                <button
                  key={b.key}
                  type="button"
                  role="tab"
                  aria-selected={b.key === active.key}
                  onClick={() => pickBoard(b.key)}
                  className={cx(
                    'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors',
                    b.key === active.key ? 'border-accent/40 bg-accent-soft text-accent-fg' : 'border-line text-muted hover:border-faint hover:text-fg',
                  )}
                >
                  {b.title}
                  <span className={cx('tabular rounded px-1 text-[11px]', b.rows.length ? 'bg-canvas' : 'text-faint')}>{b.rows.length}</span>
                </button>
              ))}
            </div>
            <p className="text-xs text-faint">{active.description}</p>
            <Board key={`${market}.${period}.${active.key}`} market={market} period={period} board={active} rows={ticking.rows} flash={ticking.flash} />
          </>
        )}
      </div>
    </div>
  )
}

function Board({
  market,
  period,
  board,
  rows,
  flash,
}: {
  market: string
  period: WatchPeriod
  board: WatchBoard
  rows: WatchBoard['rows']
  flash: (r: WatchBoard['rows'][number]) => string
}) {
  // null while checking; the notes button stays off without an AI model.
  const [aiReady, setAiReady] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    getAiStatus()
      .then((s) => !cancelled && setAiReady(s.configured))
      .catch(() => !cancelled && setAiReady(null))
    return () => {
      cancelled = true
    }
  }, [])
  const [notes, setNotes] = useState<WatchNotes | null>(null)
  const [busy, setBusy] = useState(false)
  const [noteError, setNoteError] = useState<string | null>(null)

  async function loadNotes() {
    setBusy(true)
    setNoteError(null)
    try {
      setNotes(await getWatchNotes(market, period, board.key))
    } catch (err) {
      setNoteError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (rows.length === 0) return <p className="py-6 text-center text-sm text-muted">Nothing on this list right now.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" icon="chat" onClick={loadNotes} disabled={busy || aiReady === false}>
          {busy ? 'Writing notes…' : notes ? 'Refresh AI notes' : 'AI notes on this list'}
        </Button>
        {aiReady === false && (
          <span className="text-[12px] text-faint">
            Needs an AI model:{' '}
            <Link to="/settings" className="font-medium text-accent hover:underline">
              add a key in Settings
            </Link>
          </span>
        )}
      </div>
      {noteError && <p className="text-sm text-down">{noteError}</p>}
      {notes?.summary && (
        <div className="rounded-lg border border-accent/30 bg-accent-soft/40 px-3 py-2 text-sm">
          <div className="mb-0.5 text-[11px] font-medium text-muted">AI read of this list · {relativeTime(notes.at)}</div>
          {notes.summary}
        </div>
      )}
      <ScrollBox className="pe-1" maxHeight="36rem">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.symbol} className="align-top">
                <td className="w-full max-w-0 py-2 pe-3">
                  <div className="flex items-baseline gap-2">
                    <Link to={analyzeLink(r)} className="font-mono text-sm hover:text-accent-fg">
                      {r.symbol}
                    </Link>
                    <span className="truncate text-[12px] text-faint">{r.name}</span>
                    {r.new && (
                      <span className="shrink-0" title={r.since ? `First on the lists ${r.since}` : undefined}>
                        <Badge tone="up">New</Badge>
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-muted">{r.why}</div>
                  {r.watch_low != null && r.watch_high != null && (
                    <div className="tabular text-[11px] text-faint" title="Lowest and highest close of the 20 sessions before today">
                      Watch: 20-day low {num(r.watch_low, 2)} · high {num(r.watch_high, 2)}
                      {r.rsi != null && ` · RSI ${num(r.rsi, 0)}`}
                    </div>
                  )}
                  {notes?.stocks[r.symbol] && <div className="mt-1 text-xs text-fg">{notes.stocks[r.symbol]}</div>}
                </td>
                <td className="tabular hidden whitespace-nowrap py-2 pe-3 text-end text-xs text-faint md:table-cell">{r.sector}</td>
                <td className={cx('tabular whitespace-nowrap py-2 pe-3 text-end', flash(r))}>{price(r.price, r.currency)}</td>
                <td className={cx('tabular py-2 text-end', trendClass(r.change_percent))}>{pct(r.change_percent)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollBox>
    </div>
  )
}
