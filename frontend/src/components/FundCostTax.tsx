import { useEffect, useMemo, useState } from 'react'
import { getFundCost, type FundCost, type FundTaxRules } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { Field, Input, Skeleton } from './ui'

const inr = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`

function monthsBetween(from: string, to: Date): number {
  const f = new Date(`${from}T00:00:00`)
  return (to.getFullYear() - f.getFullYear()) * 12 + (to.getMonth() - f.getMonth()) - (to.getDate() < f.getDate() ? 1 : 0)
}

/** Tax on redeeming now under the fund's rules; null when the inputs are incomplete. */
function estimateTax(rules: FundTaxRules, cls: string, invested: number, value: number, bought: string, slab: number, today = new Date()) {
  if (!(invested > 0) || !(value >= 0) || !bought) return null
  const months = monthsBetween(bought, today)
  if (months < 0) return null
  const gain = value - invested
  if (gain <= 0) return { months, gain, rate: 0, tax: 0, taxable: 0, basis: 'A loss: no tax (it can be set off against other gains).' }
  let rate: number
  let taxable = gain
  let basis: string
  if (cls === 'equity') {
    if (months <= (rules.short_months ?? 12)) {
      rate = rules.short_rate ?? 20
      basis = `Held ${months} months (12 or less): short-term, ${rate}%.`
    } else {
      rate = rules.long_rate ?? 12.5
      taxable = Math.max(0, gain - rules.exemption)
      basis = `Held ${months} months: long-term, ${rate}% on gains above ${inr(rules.exemption)} (if you have no other equity gains this year).`
    }
  } else if (cls === 'debt') {
    const before2023 = bought < '2023-04-01'
    if (before2023 && months > 24) {
      rate = 12.5
      basis = `Bought before 1 April 2023 and held ${months} months: 12.5%.`
    } else {
      rate = slab
      basis = `Taxed at your slab rate (${slab}%) however long you hold.`
    }
  } else if (months > (rules.short_months ?? 24)) {
    rate = rules.long_rate ?? 12.5
    basis = `Held ${months} months (over 24): ${rate}%.`
  } else {
    rate = slab
    basis = `Held ${months} months (24 or less): your slab rate (${slab}%).`
  }
  const tax = (taxable * rate) / 100 * (1 + rules.cess / 100)
  return { months, gain, rate, tax, taxable, basis }
}

/** What the plan choice costs over time, and the tax on redeeming now. */
export default function FundCostTax({ code }: { code: string }) {
  const [data, setData] = useState<FundCost | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [invested, setInvested] = useState('100000')
  const [value, setValue] = useState('130000')
  const [bought, setBought] = useState(() => {
    const d = new Date()
    d.setFullYear(d.getFullYear() - 2)
    return d.toISOString().slice(0, 10)
  })
  const [slab, setSlab] = useState('30')

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError(null)
    getFundCost(code, controller.signal)
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [code])

  const est = useMemo(
    () => (data?.tax && data.tax_class ? estimateTax(data.tax, data.tax_class, Number(invested), Number(value), bought, Number(slab)) : null),
    [data, invested, value, bought, slab],
  )

  return (
    <section id="fund-cost" data-section="Cost & tax" className="scroll-mt-6 space-y-5 border-t border-line pt-6">
      <div>
        <h3 className="text-sm font-semibold">Cost & tax</h3>
        <p className="text-xs text-muted">What the plan you pick costs over the years, and the tax if you redeem now.</p>
      </div>
      {error ? (
        <p className="text-xs text-faint">Unavailable right now: {error}</p>
      ) : !data ? (
        <Skeleton className="h-32 w-full" />
      ) : data.status !== 'ok' ? (
        <p className="text-xs text-faint">{data.note}</p>
      ) : (
        <>
          {data.plans && data.cost ? (
            <div className="space-y-2 rounded-lg bg-canvas p-4">
              <div className="text-sm">
                Over the last {data.plans.years} years the <b>Direct</b> plan returned {num(data.plans.direct, 2)}% a year and the <b>Regular</b>{' '}
                plan {num(data.plans.regular, 2)}%: Regular costs about <b className={cx(data.plans.gap > 0.5 && 'text-down')}>{num(data.plans.gap, 2)}% a year</b> more
                (the distributor's commission).
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-md border border-line p-3 text-sm">
                  <div className="text-xs text-faint">{inr(data.cost.lumpsum)} invested once, {data.cost.years} years</div>
                  <div className="tabular mt-1">
                    Direct {inr(data.cost.lumpsum_direct)} · Regular {inr(data.cost.lumpsum_regular)}
                  </div>
                  <div className="tabular text-xs text-down">Regular leaves you {inr(data.cost.lumpsum_direct - data.cost.lumpsum_regular)} poorer</div>
                </div>
                <div className="rounded-md border border-line p-3 text-sm">
                  <div className="text-xs text-faint">{inr(data.cost.sip)} a month (SIP), {data.cost.years} years</div>
                  <div className="tabular mt-1">
                    Direct {inr(data.cost.sip_direct)} · Regular {inr(data.cost.sip_regular)}
                  </div>
                  <div className="tabular text-xs text-down">Regular leaves you {inr(data.cost.sip_direct - data.cost.sip_regular)} poorer</div>
                </div>
              </div>
              <p className="text-[12px] text-faint">
                Gap measured from both plans' NAVs ({data.plans.from} to {data.plans.to}); the rupee figures assume {num(data.cost.assumed_return, 0)}% a year, an
                illustration, not a forecast.
              </p>
            </div>
          ) : (
            <p className="text-xs text-faint">No matching {data.plan === 'Direct' ? 'Regular' : 'Direct'} plan with enough history to compare.</p>
          )}

          {data.tax && (
            <div className="space-y-3">
              <div className="text-xs font-medium text-muted">
                Tax if you redeem now · {data.tax.label}
              </div>
              <p className="text-xs text-muted">{data.tax.text}</p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Field label="Invested (₹)">
                  <Input type="number" min="0" step="any" value={invested} onChange={(e) => setInvested(e.target.value)} />
                </Field>
                <Field label="Worth now (₹)">
                  <Input type="number" min="0" step="any" value={value} onChange={(e) => setValue(e.target.value)} />
                </Field>
                <Field label="Bought on">
                  <Input type="date" value={bought} onChange={(e) => setBought(e.target.value)} />
                </Field>
                <Field label="Your slab rate (%)">
                  <Input type="number" min="0" max="45" step="any" value={slab} onChange={(e) => setSlab(e.target.value)} />
                </Field>
              </div>
              {est && (
                <div className="rounded-lg bg-canvas p-4 text-sm">
                  <div className="tabular">
                    Gain {inr(est.gain)} · tax about <b>{inr(est.tax)}</b> · you keep {inr(Number(value) - est.tax)}
                  </div>
                  <div className="mt-1 text-xs text-muted">
                    {est.basis} Includes {data.tax.cess}% cess; surcharge and other gains of the year are left out.
                  </div>
                </div>
              )}
              <p className="text-[12px] text-faint">Rules in force from {data.tax.rules_from}. A guide, not tax advice: check with a tax professional.</p>
            </div>
          )}
        </>
      )}
    </section>
  )
}
