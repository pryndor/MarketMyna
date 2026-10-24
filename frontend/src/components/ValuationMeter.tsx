import { useEffect, useState } from 'react'
import { getValuation, type Valuation } from '../api/compare'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import InsightLoader from './InsightLoader'
import { Card, CardBody, CardHeader } from './ui'

// Where today's price sits against the stock's sector (P/E, P/B, P/S vs the
// sector median of the market's largest companies) plus a growth check.
// Says "below / in line / above sector" with the numbers, never a bare
// "overvalued" (src/core/compliance.py: no verdicts on a stock).

const WORDS = { below: 'Below sector', in_line: 'In line with sector', above: 'Above sector' } as const
// Neutral tones, so the zones don't read as buy / sell colours.
const ZONES = ['bg-line-strong/40', 'bg-line-strong/70', 'bg-line-strong/40']

// Needle scale: ratio 0.4x .. 2.5x on a log axis, so 0.5x and 2x sit equally far from 1x.
const MIN = 0.4
const MAX = 2.5
const pos = (r: number) => (Math.log(Math.min(Math.max(r, MIN), MAX) / MIN) / Math.log(MAX / MIN)) * 100

export default function ValuationMeter({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Valuation | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getValuation(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(errorMessage(e)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto') return null

  const below = data?.bands?.below ?? 0.8
  const above = data?.bands?.above ?? 1.2
  const z = data?.zone ?? null

  return (
    <Card id="section-valuation" section="Valuation meter">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Valuation meter
            {z && <span className={'rounded-md bg-raised px-2 py-0.5 text-xs font-semibold text-fg'}>{WORDS[z]}</span>}
          </span>
        }
        description={
          data?.status === 'ok'
            ? `Today's price vs ${data.sector} companies (${data.peers} profitable peers among ${data.universe})`
            : "Today's price against the company's sector"
        }
      />
      <CardBody className="space-y-5">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && (
          <InsightLoader
            className="min-h-44"
            steps={['Reading the company’s P/E, book value and sales…', 'Building sector medians from the largest companies…', 'Placing today’s price on the meter…']}
          />
        )}
        {data?.status === 'unavailable' && <p className="text-sm text-muted">{data.reason}</p>}
        {data?.status === 'ok' && data.position != null && (
          <>
            <div>
              <div className="relative h-3 overflow-hidden rounded-full bg-raised">
                <span className={cx('absolute inset-y-0 left-0', ZONES[0])} style={{ width: `${pos(below)}%` }} />
                <span className={cx('absolute inset-y-0', ZONES[1])} style={{ left: `${pos(below)}%`, width: `${pos(above) - pos(below)}%` }} />
                <span className={cx('absolute inset-y-0 right-0', ZONES[2])} style={{ left: `${pos(above)}%` }} />
              </div>
              <div className="relative h-0">
                <span
                  className="absolute -top-5 h-7 w-1 -translate-x-1/2 rounded-full bg-fg shadow"
                  style={{ left: `${pos(data.position)}%` }}
                  aria-hidden="true"
                />
              </div>
              <div className="mt-3 grid grid-cols-3 text-[12px] text-faint">
                <span>{WORDS.below}</span>
                <span className="text-center">{WORDS.in_line}</span>
                <span className="text-end">{WORDS.above}</span>
              </div>
              <p className="mt-2 text-sm">
                Priced at <span className="tabular font-semibold">{num(data.position, 2)}×</span> its sector on average
                {' '}
                <span className="text-muted">
                  (below {below}× = {WORDS.below.toLowerCase()}, above {above}× = {WORDS.above.toLowerCase()})
                </span>
              </p>
            </div>

            <table className="tabular w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-1.5 text-start font-medium">Measure</th>
                  <th className="py-1.5 text-end font-medium">This stock</th>
                  <th className="py-1.5 text-end font-medium">
                    Sector<span className="hidden sm:inline"> median</span>
                  </th>
                  <th className="py-1.5 text-end font-medium">× sector</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.multiples?.map((m) => (
                  <tr key={m.key}>
                    <td className="py-1.5">{m.label}</td>
                    <td className="py-1.5 text-end">{m.value != null && m.value > 0 ? num(m.value, 1) : '—'}</td>
                    <td className="py-1.5 text-end text-muted">{m.sector_median != null ? num(m.sector_median, 1) : '—'}</td>
                    <td className="py-1.5 text-end font-medium">{m.ratio != null ? `${num(m.ratio, 2)}×` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {data?.garp && data.status === 'ok' && (
          <div className="rounded-lg bg-canvas p-4">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-medium">Growth at a reasonable price</span>
              <span className="text-xs text-muted">
                Meets {data.garp.passed} of {data.garp.total} rules
                {data.garp.missing ? ` (${data.garp.missing} without data)` : ''} · PEG{' '}
                <span className="tabular font-semibold text-fg">{data.garp.peg != null ? num(data.garp.peg, 2) : '—'}</span>
              </span>
            </div>
            <ul className="grid gap-x-10 gap-y-1 text-xs sm:grid-cols-2">
              {data.garp.rules.map((r) => (
                <li key={r.rule} className="flex items-center justify-between gap-2">
                  <span className={r.pass ? 'text-fg' : 'text-muted'}>
                    <span className={cx('me-1.5 font-semibold', r.pass ? 'text-up' : 'text-faint')}>
                      {r.pass == null ? '–' : r.pass ? '✓' : '✗'}
                    </span>
                    {r.rule}
                  </span>
                  <span className="tabular text-faint">{r.value != null ? num(r.value, 1) : 'no data'}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[12px] text-faint">
              PEG = P/E ÷ earnings growth %. Around 1 means the price and the growth match; above 2 the price runs ahead of growth.
            </p>
          </div>
        )}

        {data?.status === 'ok' && (
          <p className="text-[12px] text-faint">
            A comparison with the company’s sector at today’s price, not a fair-value estimate or advice. A company can deserve a
            higher multiple (faster growth, stronger brand) or be cheap for a reason. Fundamentals from our market data feed, latest
            reported; sector medians refresh every few hours.
          </p>
        )}
      </CardBody>
    </Card>
  )
}
