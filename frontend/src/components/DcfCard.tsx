import { useEffect, useMemo, useState } from 'react'
import { downloadDcfModel, getDcf, type Dcf } from '../api/stocks'
import { impliedGrowth, modelValue } from '../lib/dcf'
import { compact, errorMessage, num } from '../lib/format'
import { toast } from '../lib/toast'
import { Button, Card, CardBody, CardHeader, Input, Skeleton, Stat } from './ui'

// A model under the viewer's own assumptions, worded as arithmetic ("price is
// x% above the model value"), never as a buy / sell call
// (docs/future/sebi-compliance-mode.md).

type Rates = { growth: string; discount: string; terminal: string }

const toPct = (x: number) => (x * 100).toFixed(1)
const fromPct = (s: string) => {
  const v = parseFloat(s)
  return Number.isFinite(v) ? v / 100 : null
}

function gapText(price: number | null, value: number | null): string {
  if (!price || !value || value <= 0) return 'No positive model value under these assumptions'
  const gap = (price / value - 1) * 100
  if (Math.abs(gap) < 0.5) return 'Price is about equal to the model value'
  return `Price is ${Math.abs(gap).toFixed(1)}% ${gap > 0 ? 'above' : 'below'} the model value`
}

/** Discounted cash flow with editable assumptions, reverse DCF and the Graham number. */
export default function DcfCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Dcf | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rates, setRates] = useState<Rates | null>(null)
  const [downloading, setDownloading] = useState(false)

  async function downloadModel() {
    const growth = fromPct(rates?.growth ?? '')
    const discount = fromPct(rates?.discount ?? '')
    const terminal = fromPct(rates?.terminal ?? '')
    if (growth == null || discount == null || terminal == null) return
    setDownloading(true)
    try {
      await downloadDcfModel(symbol, market, { growth, discount, terminal })
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setDownloading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    setRates(null)
    getDcf(symbol, market)
      .then((d) => {
        if (cancelled) return
        setData(d)
        if (d.dcf) setRates({ growth: toPct(d.dcf.defaults.growth), discount: toPct(d.dcf.defaults.discount), terminal: toPct(d.dcf.defaults.terminal) })
      })
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  const result = useMemo(() => {
    const d = data?.dcf
    if (!d || !rates) return null
    const growth = fromPct(rates.growth)
    const discount = fromPct(rates.discount)
    const terminal = fromPct(rates.terminal)
    if (growth == null || discount == null || terminal == null) return { invalid: 'Enter a number in each box.' }
    if (discount <= terminal) return { invalid: 'The discount rate must be above the terminal growth rate.' }
    const base = { fcf: d.base_fcf, discount, terminal, netCash: d.net_cash, shares: d.shares, highYears: d.defaults.high_years, totalYears: d.defaults.total_years }
    return {
      value: modelValue({ ...base, growth }),
      implied: data?.price ? impliedGrowth(data.price, base) : null,
    }
  }, [data, rates])

  if (market === 'crypto') return null

  const d = data?.dcf
  const ccy = data?.currency ? ` ${data.currency}` : ''
  const edited =
    d && rates && (rates.growth !== toPct(d.defaults.growth) || rates.discount !== toPct(d.defaults.discount) || rates.terminal !== toPct(d.defaults.terminal))

  return (
    <Card id="section-dcf" section="DCF & Graham">
      <CardHeader title="Discounted cash flow" description="What the cash flows are worth under your assumptions, and what today's price assumes" />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !data ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <>
            {d && rates && result ? (
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  {(
                    [
                      ['growth', `Growth, years 1-${d.defaults.high_years}`, 'Free cash flow growth a year; fades to the terminal rate by year 10'],
                      ['discount', 'Discount rate', 'Return you require a year'],
                      ['terminal', 'Terminal growth', 'Growth a year after year 10, for ever'],
                    ] as const
                  ).map(([key, label, hint]) => (
                    <label key={key} className="block min-w-0">
                      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="number"
                          inputMode="decimal"
                          step="0.5"
                          value={rates[key]}
                          onChange={(e) => setRates({ ...rates, [key]: e.target.value })}
                          className="w-full"
                          aria-label={`${label} (%)`}
                        />
                        <span className="text-sm text-muted">%</span>
                      </div>
                      <span className="mt-1 block text-[11px] text-faint">{hint}</span>
                    </label>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  {edited && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setRates({ growth: toPct(d.defaults.growth), discount: toPct(d.defaults.discount), terminal: toPct(d.defaults.terminal) })}
                    >
                      Reset to defaults
                    </Button>
                  )}
                  {!('invalid' in result) && (
                    <Button size="sm" variant="secondary" icon="download" loading={downloading} onClick={downloadModel}>
                      Excel model
                    </Button>
                  )}
                </div>
                {'invalid' in result ? (
                  <p className="text-sm text-warn">{result.invalid}</p>
                ) : (
                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                    <Stat label="Model value / share" value={`${num(result.value)}${ccy}`} sub={gapText(data.price, result.value)} />
                    <Stat label="Price" value={`${num(data.price)}${ccy}`} />
                    <Stat
                      label="Growth the price implies"
                      value={result.implied != null ? `${(result.implied * 100).toFixed(1)}%` : '—'}
                      sub={result.implied != null ? `a year for ${d.defaults.high_years} years, at these discount and terminal rates` : 'outside -50% to +100% a year'}
                    />
                    <Stat
                      label="Free cash flow used"
                      value={`${compact(d.base_fcf)}${ccy}`}
                      sub={`${d.base_label}, after capex${d.sbc ? ` and ${compact(d.sbc)} stock-based pay` : ''}; net ${d.net_cash >= 0 ? 'cash' : 'debt'} ${compact(Math.abs(d.net_cash))} (incl. investments)`}
                    />
                  </div>
                )}
              </div>
            ) : (
              data.note && <p className="text-sm text-muted">{data.note}</p>
            )}

            {data.graham && (
              <div className="border-t border-line pt-4">
                <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <Stat
                    label="Graham number"
                    value={`${num(data.graham.value)}${ccy}`}
                    sub={
                      data.graham.vs_price_pct != null
                        ? `Price is ${Math.abs(data.graham.vs_price_pct).toFixed(1)}% ${data.graham.vs_price_pct >= 0 ? 'above' : 'below'} it`
                        : undefined
                    }
                  />
                  <Stat label="EPS (12 months)" value={num(data.graham.eps)} />
                  <Stat label="Book value / share" value={num(data.graham.book_value_per_share)} />
                </div>
                <p className="mt-2 text-[12px] text-faint">
                  √(22.5 × EPS × book value per share): Benjamin Graham's ceiling for a defensive investor (P/E 15 × P/B 1.5). Suits
                  asset-heavy, steadily profitable companies; it understates firms whose value sits in brands, software or people.
                </p>
              </div>
            )}

            <p className="text-[12px] text-faint">
              {d &&
                `Two-stage model: free cash flow (operating cash flow minus capex) grows at your rate for ${d.defaults.high_years} years, fades to the terminal rate by year ${d.defaults.total_years}, then a terminal value; net cash is added and the total divided by shares. Defaults are starting points (growth = recent revenue growth, capped 0-15%), not forecasts. `}
              Source: {data.source}
              {d?.converted_from && `; cash flows converted from ${d.converted_from} at the ECB rate`}. Arithmetic on published figures, not advice.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
