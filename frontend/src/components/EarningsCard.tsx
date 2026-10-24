import { useEffect, useState } from 'react'
import { getEarnings, type Earnings, type EarningsEvent } from '../api/compare'
import { cx } from '../lib/cx'
import { errorMessage, num, pct, trendClass } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

function when(days: number | null): string {
  if (days == null) return ''
  if (days <= 0) return 'today'
  if (days === 1) return 'tomorrow'
  return `in ${days} days`
}

function verdict(e: EarningsEvent): { text: string; tone: string } | null {
  if (e.surprise == null) return null
  if (e.unusual) return { text: 'data looks off', tone: 'text-faint' }
  if (Math.abs(e.surprise) < 0.5) return { text: 'in line', tone: 'text-muted' }
  return e.surprise > 0 ? { text: `beat ${num(e.surprise, 1)}%`, tone: 'text-up' } : { text: `missed ${num(-e.surprise, 1)}%`, tone: 'text-down' }
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-canvas p-3">
      <div className="text-xs text-faint">{label}</div>
      <div className="tabular mt-0.5 text-base font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted">{sub}</div>}
    </div>
  )
}

/** Earnings preview before a report (date, past reactions, options-implied move,
 * what to watch) and the review once results are out (actual vs expected, the move). */
export default function EarningsCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Earnings | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getEarnings(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto' || (data && !data.available)) return null
  const latest = data?.latest
  const v = latest ? verdict(latest) : null
  const s = data?.stats

  return (
    <Card id="section-earnings" section="Earnings">
      <CardHeader
        title="Earnings"
        icon="clock"
        description={
          !data
            ? 'Next report, past reactions and what to watch'
            : latest
              ? `Results are out (${latest.date})`
              : data.next
                ? `Next report ${data.next.date}, ${when(data.days_to_next)}`
                : 'No report date announced yet'
        }
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-sm text-muted">Earnings data unavailable: {error}</p>
        ) : !data ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            {latest && latest.actual != null && (
              <div className="rounded-lg bg-accent-soft/40 px-4 py-3 ring-1 ring-accent/30">
                <div className="text-sm font-semibold">Results are out</div>
                <div className="tabular mt-1 text-sm">
                  EPS {num(latest.actual, 2)}
                  {latest.estimate != null && <span className="text-muted"> vs {num(latest.estimate, 2)} expected</span>}
                  {v && <span className={cx('ms-1 font-medium', v.tone)}>({v.text})</span>}
                  {latest.reaction && (
                    <span className="ms-2">
                      · stock <span className={trendClass(latest.reaction.move)}>{pct(latest.reaction.move, 1)}</span> on the day
                    </span>
                  )}
                </div>
                {s && latest.reaction && (
                  <p className="mt-1 text-xs text-muted">
                    A typical results-day move for this stock is ±{num(s.avg_abs_move, 1)}%, so this was{' '}
                    {Math.abs(latest.reaction.move) > s.avg_abs_move * 1.5 ? 'a bigger reaction than usual' : Math.abs(latest.reaction.move) < s.avg_abs_move * 0.5 ? 'a muted reaction' : 'about a normal reaction'}.
                  </p>
                )}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {data.next && (
                <Tile
                  label="Next report"
                  value={new Date(`${data.next.date}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                  sub={`${when(data.days_to_next)}${data.next.estimate != null ? ` · EPS est. ${num(data.next.estimate, 2)}` : ''}`}
                />
              )}
              {data.implied && (
                <Tile
                  label="Options price in"
                  value={`±${num(data.implied.move, 1)}%`}
                  sub={`At-the-money straddle, ${data.implied.expiry} expiry`}
                />
              )}
              {s && <Tile label="Typical move" value={`±${num(s.avg_abs_move, 1)}%`} sub={`Last ${s.reports} reports · up ${s.up_days} of ${s.reports}`} />}
              {s && s.beats + s.misses > 0 && (
                <Tile label="Beat estimates" value={`${s.beats} of ${s.beats + s.misses}`} sub={`Biggest moves ${pct(s.biggest_up, 1)} / ${pct(s.biggest_down, 1)}`} />
              )}
            </div>

            {data.implied && s && (
              <p className="text-xs text-muted">
                The options market expects a move of about ±{num(data.implied.move, 1)}% around this report, against a typical ±{num(s.avg_abs_move, 1)}% in the past:{' '}
                {data.implied.move > s.avg_abs_move * 1.25
                  ? 'traders are bracing for a bigger move than usual.'
                  : data.implied.move < s.avg_abs_move * 0.75
                    ? 'a calmer reaction than usual is priced in.'
                    : 'roughly what it has done before.'}
              </p>
            )}
            {s && (s.avg_move_on_beat != null || s.avg_move_on_miss != null) && (
              <p className="text-xs text-muted">
                After a beat the stock moved {s.avg_move_on_beat != null ? pct(s.avg_move_on_beat, 1) : '—'} on average; after a miss{' '}
                {s.avg_move_on_miss != null ? pct(s.avg_move_on_miss, 1) : '—'}.
                {s.avg_move_on_beat != null && s.avg_move_on_beat < 0 && ' Beating estimates has not been enough to lift it: expectations run high.'}
              </p>
            )}
            {data.consensus?.eps.avg != null && (
              <p className="text-xs text-muted">
                {data.consensus.period} consensus EPS {num(data.consensus.eps.avg, 2)}
                {data.consensus.eps.analysts ? ` from ${data.consensus.eps.analysts} analysts` : ''}
                {data.consensus.trend.change_90d != null && `, ${pct(data.consensus.trend.change_90d, 1)} over 90 days`}. Full detail in Analyst estimates.
              </p>
            )}

            <div>
              <div className="mb-2 text-xs font-medium text-muted">What to watch{data.sector ? ` (${data.sector})` : ''}</div>
              <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
                {data.watch.map((w) => (
                  <li key={w} className="flex gap-2">
                    <span className="text-accent">•</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>

            {data.history.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-faint">
                      <th className="py-1.5 pe-3 text-start font-medium">Reported</th>
                      <th className="px-2 py-1.5 text-end font-medium">EPS est.</th>
                      <th className="px-2 py-1.5 text-end font-medium">Actual</th>
                      <th className="px-2 py-1.5 text-end font-medium">Result</th>
                      <th className="py-1.5 ps-2 text-end font-medium" title="Last close before the announcement to the first close after it">Stock move</th>
                    </tr>
                  </thead>
                  <tbody className="tabular">
                    {data.history.slice(0, 8).map((e) => {
                      const r = verdict(e)
                      return (
                        <tr key={e.at} className="border-t border-line">
                          <td className="whitespace-nowrap py-2 pe-3 text-start">{e.date}</td>
                          <td className="px-2 py-2 text-end text-muted">{num(e.estimate, 2)}</td>
                          <td className="px-2 py-2 text-end">{num(e.actual, 2)}</td>
                          <td className={cx('whitespace-nowrap px-2 py-2 text-end', r?.tone)} title={e.unusual ? 'The estimate and actual look like different periods (e.g. yearly vs quarterly): left out of the averages' : undefined}>
                            {r?.text ?? '—'}
                          </td>
                          <td className={cx('py-2 ps-2 text-end', e.reaction ? trendClass(e.reaction.move) : 'text-faint')}>
                            {e.reaction ? pct(e.reaction.move, 1) : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-[12px] text-faint">Source: {data.source}{data.implied ? '; options chain from the exchange / market data feed' : ''}. Past reactions don't predict the next one.</p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
