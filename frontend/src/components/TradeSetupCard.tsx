import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { getLevels } from '../api/trade'
import type { SmartRow } from '../api/scheduler'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { Badge, Card, CardBody, CardHeader, Icon, SignalBadge, Skeleton } from './ui'

/** Trader view of one stock: where price sits in its normal range, the
 * expected 1-week range, ATR, RSI and volume, and one-click links into the
 * Trade workspace. Computed from daily bars (same maths as the smart report),
 * no AI. Ranges only: no support / resistance / stop to act on (src/core/compliance.py). */
export default function TradeSetupCard({ symbol, market }: { symbol: string; market: string }) {
  const [row, setRow] = useState<SmartRow | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRow(null)
    setError(null)
    getLevels(symbol, market)
      .then((r) => !cancelled && setRow(r))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  const q = new URLSearchParams({ symbol, market })
  const links: Array<[string, string, 'candles' | 'bell' | 'shield']> = [
    ['chart', 'Intraday chart', 'candles'],
    ['alerts', 'Set alert', 'bell'],
    ['size', 'Position size', 'shield'],
  ]

  return (
    <Card id="section-setup" section="Trade setup">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Trade setup {row?.trend && <Badge tone={row.trend === 'uptrend' ? 'up' : row.trend === 'downtrend' ? 'down' : 'neutral'}>{row.trend}</Badge>}
          </span>
        }
        description="Daily ranges for the next days to weeks · computed, not AI"
      />
      <CardBody>
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !row ? (
          <Skeleton className="h-36 w-full" />
        ) : (
          <Setup row={row} />
        )}
        <div className="mt-5 flex flex-wrap gap-1.5 border-t border-line pt-4">
          {links.map(([tab, label, icon]) => (
            <Link
              key={tab}
              to={`/trade?${q}&tab=${tab}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-muted hover:border-faint hover:text-fg"
            >
              <Icon name={icon} className="h-3.5 w-3.5" />
              {label}
            </Link>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

function Setup({ row }: { row: SmartRow }) {
  const price = row.price

  return (
    <div className="space-y-5">
      <LevelBar row={row} />

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <Fact label="ATR (14 days)" value={row.atr != null && price ? `${num(row.atr)} (${num((row.atr / price) * 100, 1)}%)` : '—'} hint="Average daily move: size stops in ATRs, not fixed %" />
        <Fact label="RSI (14)" value={<RsiValue rsi={row.rsi} />} />
        <Fact
          label="Volume vs 20-day"
          value={row.volume_ratio != null ? `${num(row.volume_ratio, 1)}×` : '—'}
          className={row.volume_ratio != null && row.volume_ratio >= 1.5 ? 'text-accent-fg' : undefined}
        />
        <Fact label="1-week range (≈68%)" value={`${num(row.week_low)} – ${num(row.week_high)}`} />
      </dl>

      {row.reasons && row.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {row.reasons.map((r) => (
            <span key={r} className="rounded-md bg-raised px-2 py-1 text-xs text-muted">
              {r}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/** Price on one line with its normal range and expected 1-week range. */
function LevelBar({ row }: { row: SmartRow }) {
  const values = [row.price, row.normal_low, row.normal_high, row.week_low, row.week_high].filter((v): v is number => v != null)
  if (row.price == null || values.length < 3) return null
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  if (hi <= lo) return null
  const share = (v: number) => ((v - lo) / (hi - lo)) * 100
  const at = (v: number) => `${share(v)}%`

  return (
    <div className="px-1 pt-5">
      <div className="relative h-1.5 rounded-full bg-line">
        {row.normal_low != null && row.normal_high != null && (
          <div
            className="absolute inset-y-0 rounded-full bg-accent/25"
            style={{ left: at(row.normal_low), width: `calc(${at(row.normal_high)} - ${at(row.normal_low)})` }}
            title={`Normal range (20-day band) ${num(row.normal_low)} – ${num(row.normal_high)}`}
          />
        )}
        <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: at(row.price) }} title={`Price ${num(row.price)}`}>
          <span className="block h-3.5 w-3.5 rounded-full border-2 border-canvas bg-fg" />
        </div>
      </div>
      <div className="tabular mt-8 flex justify-between text-[11px] text-faint">
        <span>{num(lo)}</span>
        <span>
          <span className="me-1 inline-block h-1.5 w-3 rounded-full bg-accent/25 align-middle" />
          normal range (20-day band) {num(row.normal_low)} – {num(row.normal_high)}
        </span>
        <span>{num(hi)}</span>
      </div>
    </div>
  )
}

function Fact({ label, value, hint, className }: { label: string; value: ReactNode; hint?: string; className?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={cx('tabular mt-0.5 font-medium', className)}>{value}</dd>
    </div>
  )
}

function RsiValue({ rsi }: { rsi?: number }) {
  if (rsi == null) return <>—</>
  const state = rsi >= 70 ? 'overbought' : rsi <= 30 ? 'oversold' : null
  return (
    <span className="inline-flex items-center gap-1.5">
      {num(rsi, 0)}
      {state && <SignalBadge value={state} />}
    </span>
  )
}
