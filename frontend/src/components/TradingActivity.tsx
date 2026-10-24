import { useEffect, useState, type ReactNode } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getTradingActivity, type BookLevel, type TradingActivity as Activity } from '../api/listings'
import { getTradeChart, type Bar as Candle } from '../api/trade'
import { cx } from '../lib/cx'
import { compact, num } from '../lib/format'
import { Skeleton } from './ui'

const LIVE_MS = 1000 // the server answers from its shared cache, so this is cheap
const IDLE_MS = 30_000 // market closed or tab hidden
const BARS_MS = 60_000

function useVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden')
  useEffect(() => {
    const on = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])
  return visible
}

/** Poll `load` every `ms` (re-read each round), keeping the last good answer. */
function usePoll<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[], ms: (data: T | null) => number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setData(null)
    setError(null)
    let stop = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | undefined
    let last: T | null = null
    const tick = () => {
      controller = new AbortController()
      load(controller.signal)
        .then((d) => {
          last = d
          setData(d)
          setError(null)
        })
        .catch((e: unknown) => {
          if (!controller?.signal.aborted) setError(e instanceof Error ? e.message : 'Could not load')
        })
        .finally(() => {
          if (!stop) timer = setTimeout(tick, ms(last))
        })
    }
    tick()
    return () => {
      stop = true
      controller?.abort()
      clearTimeout(timer)
    }
  }, deps)
  return { data, error }
}

function BookSide({ levels, side, max }: { levels: BookLevel[]; side: 'buy' | 'sell'; max: number }) {
  const rows = [...levels, ...Array(Math.max(0, 5 - levels.length)).fill(null)] as Array<BookLevel | null>
  return (
    <table className="tabular w-full text-xs">
      <thead className="text-faint">
        <tr>
          {side === 'buy' ? (
            <>
              <th className="py-1 text-start font-medium">Orders</th>
              <th className="py-1 text-end font-medium">Qty</th>
              <th className="py-1 text-end font-medium">Bid</th>
            </>
          ) : (
            <>
              <th className="py-1 text-start font-medium">Offer</th>
              <th className="py-1 text-end font-medium">Qty</th>
              <th className="py-1 text-end font-medium">Orders</th>
            </>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((lv, i) => {
          const width = lv && max ? `${Math.max(4, (lv.quantity / max) * 100)}%` : '0%'
          const bar = (
            <span
              aria-hidden="true"
              className={cx('absolute inset-y-0.5 rounded-sm', side === 'buy' ? 'end-0 bg-up-soft' : 'start-0 bg-down-soft')}
              style={{ width }}
            />
          )
          return (
            <tr key={i} className="relative">
              {side === 'buy' ? (
                <>
                  <td className="py-0.5 text-start text-faint">{lv?.orders ?? '—'}</td>
                  <td className="py-0.5 text-end">{lv ? lv.quantity.toLocaleString() : '—'}</td>
                  <td className="relative py-0.5 ps-2 text-end font-medium text-up">
                    {bar}
                    <span className="relative">{lv ? num(lv.price) : '—'}</span>
                  </td>
                </>
              ) : (
                <>
                  <td className="relative py-0.5 pe-2 text-start font-medium text-down">
                    {bar}
                    <span className="relative">{lv ? num(lv.price) : '—'}</span>
                  </td>
                  <td className="py-0.5 text-end">{lv ? lv.quantity.toLocaleString() : '—'}</td>
                  <td className="py-0.5 text-end text-faint">{lv?.orders ?? '—'}</td>
                </>
              )}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Figure({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className="tabular truncate text-sm font-semibold">{value}</div>
      {sub && <div className="truncate text-[11px] text-faint">{sub}</div>}
    </div>
  )
}

/** Live volume for every market; for Indian shares also the pending buy /
 * sell quantity, the best five bids and offers (broker feed) and last
 * session's delivery %. */
export default function TradingActivity({ symbol, market }: { symbol: string; market: string }) {
  const visible = useVisible()
  const india = market === 'india'
  const live = usePoll<Activity>(
    (signal) => getTradingActivity(symbol, market, signal),
    [symbol, market, visible],
    (d) => (visible && d?.open ? LIVE_MS : IDLE_MS),
  )
  const bars = usePoll<Candle[]>(
    async () => (await getTradeChart(symbol, market, '5m', '1d', [])).bars,
    [symbol, market, visible],
    () => (visible ? BARS_MS : 5 * BARS_MS),
  )

  const q = live.data?.quote
  const book = q?.depth
  const broker = q?.buy_qty != null && q?.sell_qty != null
  const pending = broker ? q!.buy_qty! + q!.sell_qty! : 0
  // Outside the session the exchange clears pending orders: both sides read 0.
  const hasBook = pending > 0
  const buyShare = pending ? (q!.buy_qty! / pending) * 100 : 50
  const maxLevel = Math.max(1, ...(book?.buy ?? []).map((l) => l.quantity), ...(book?.sell ?? []).map((l) => l.quantity))
  const del = live.data?.delivery
  const day = bars.data ?? []
  const lastDay = day.length ? new Date(day[day.length - 1].time * 1000).toISOString().slice(0, 10) : null
  const session = day.filter((b) => new Date(b.time * 1000).toISOString().slice(0, 10) === lastDay)

  return (
    <div className="mt-5 space-y-4 border-t border-line pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Trading activity</h3>
        {live.data && (
          <span className="flex items-center gap-1.5 text-[11px] text-faint">
            <span className={cx('h-1.5 w-1.5 rounded-full', live.data.open ? 'animate-pulse bg-up' : 'bg-faint')} />
            {live.data.open ? `Live · ${live.data.source}` : 'Market closed · last session'}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
        <Figure
          label="Volume today"
          value={live.data ? compact(q?.volume) : <Skeleton className="mt-1 h-5 w-16" />}
          sub={q?.last_qty ? `last trade ${q.last_qty.toLocaleString()} shares` : ' '}
        />
        {q?.avg_price != null && <Figure label="Average traded price" value={num(q.avg_price)} sub="volume-weighted, today" />}
        {india && (
          <Figure
            label="Delivery"
            value={del?.percent != null ? `${num(del.percent, 1)}%` : del?.loading ? <Skeleton className="mt-1 h-5 w-12" /> : '—'}
            sub={
              del?.percent != null
                ? `${compact(del.delivered)} of ${compact(del.traded)} shares kept · ${del.date}`
                : del?.loading
                  ? 'loading the exchange file…'
                  : 'not published for this share'
            }
          />
        )}
        {q?.lower_circuit != null && q?.upper_circuit != null && (
          <Figure label="Circuit band" value={`${num(q.lower_circuit)} – ${num(q.upper_circuit)}`} sub="price can't move outside today" />
        )}
      </div>

      {india && (
        hasBook ? (
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex justify-between text-xs">
                <span className="text-up">
                  Buyers waiting <b className="tabular">{compact(q!.buy_qty)}</b> ({num(buyShare, 0)}%)
                </span>
                <span className="text-down">
                  ({num(100 - buyShare, 0)}%) <b className="tabular">{compact(q!.sell_qty)}</b> sellers waiting
                </span>
              </div>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-raised" role="img" aria-label={`Buy ${num(buyShare, 0)}%, sell ${num(100 - buyShare, 0)}%`}>
                <div className="bg-up transition-[width] duration-500" style={{ width: `${buyShare}%` }} />
                <div className="flex-1 bg-down" />
              </div>
              <p className="mt-1 text-[11px] text-faint">Total shares in pending buy and sell orders on the exchange right now.</p>
            </div>
            {book && (
              <div className="grid gap-4 sm:grid-cols-2">
                <BookSide levels={book.buy} side="buy" max={maxLevel} />
                <BookSide levels={book.sell} side="sell" max={maxLevel} />
              </div>
            )}
          </div>
        ) : (
          live.data && (
            <p className="text-xs text-faint">
              {broker
                ? 'No pending orders right now: the order book fills during market hours (9:15 am – 3:30 pm IST).'
                : 'Pending buy / sell quantity and the order book show when the live broker feed is on for Indian shares.'}
            </p>
          )
        )
      )}

      <div>
        <div className="mb-1 flex items-baseline justify-between text-xs">
          <span className="font-medium text-muted">Volume every 5 minutes</span>
          {lastDay && <span className="text-[11px] text-faint">{lastDay} · updates every minute</span>}
        </div>
        <div className="h-28">
          {session.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={session} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <XAxis
                  dataKey="time"
                  tickFormatter={(t: number) => new Date(t * 1000).toISOString().slice(11, 16)}
                  tick={{ fill: 'var(--color-faint)', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={40}
                />
                <YAxis width={40} tickFormatter={(v: number) => compact(v)} tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip
                  cursor={{ fill: 'var(--color-raised)' }}
                  contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(t) => new Date(Number(t) * 1000).toISOString().slice(11, 16)}
                  formatter={(v) => [Number(v).toLocaleString(), 'Shares']}
                />
                <Bar dataKey="volume" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                  {session.map((b) => (
                    <Cell key={b.time} fill={b.close >= b.open ? 'var(--color-up)' : 'var(--color-down)'} fillOpacity={0.75} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : bars.error ? (
            <div className="grid h-full place-items-center text-xs text-faint">Intraday volume unavailable</div>
          ) : bars.data ? (
            <div className="grid h-full place-items-center text-xs text-faint">No trades yet this session</div>
          ) : (
            <Skeleton className="h-full w-full" />
          )}
        </div>
        <p className="mt-1 text-[11px] text-faint">Green: the price closed higher in that 5 minutes, red: lower.</p>
      </div>
    </div>
  )
}
