import { useEffect, useMemo, useState } from 'react'
import { getFundAnalytics } from '../api/listings'
import { chance, monthlyNeeded, project } from '../lib/montecarlo'
import { num } from '../lib/format'
import { Field, Input } from './ui'

const inr = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`
const FALLBACK_VOL = 0.15

/** Goal planner: the SIP needed for an 80% chance of a target, and the chance
 * with the current SIP, from 2,000 simulated paths at this fund's own volatility. */
export default function SipGoal({ code, monthly, expected }: { code: string; monthly: number; expected: number }) {
  const [goal, setGoal] = useState(2500000)
  const [years, setYears] = useState(10)
  const [start, setStart] = useState(0)
  const [vol, setVol] = useState<number | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setVol(null)
    getFundAnalytics(code, controller.signal)
      .then((a) => setVol(a.risk?.volatility && a.risk.volatility > 0.005 ? a.risk.volatility : FALLBACK_VOL))
      .catch(() => !controller.signal.aborted && setVol(FALLBACK_VOL))
    return () => controller.abort()
  }, [code])

  const result = useMemo(() => {
    if (vol == null || !(goal > 0) || !(years > 0)) return null
    const base = { start, years, expectedReturn: expected / 100, volatility: vol }
    const p = project({ ...base, monthly })
    const last = p.bands[p.bands.length - 1]
    return { need: monthlyNeeded(base, goal, 0.8), odds: chance(p.finals, goal), last }
  }, [vol, goal, years, start, monthly, expected])

  const field = (label: string, value: number, set: (v: number) => void, step = 1) => (
    <Field label={label}>
      <Input type="number" min={0} step={step} value={value} onChange={(e) => set(Math.max(0, Number(e.target.value) || 0))} />
    </Field>
  )

  return (
    <div className="space-y-3 rounded-lg bg-canvas p-4">
      <div className="text-xs font-medium text-muted">Reach a goal</div>
      <div className="grid grid-cols-3 gap-3">
        {field('Goal (₹)', goal, setGoal, 100000)}
        {field('In years', years, setYears)}
        {field('Already have (₹)', start, setStart, 10000)}
      </div>
      {!result ? (
        <p className="text-xs text-faint">Working out the odds…</p>
      ) : (
        <div className="space-y-2 text-sm">
          <div>
            For an 80% chance of {inr(goal)} in {years} years you'd need about{' '}
            <b className="tabular">{result.need != null ? `${inr(result.need)} a month` : 'more than any SIP can reach'}</b>.
          </div>
          <div>
            With {inr(monthly)} a month the chance is <b className="tabular">{num(result.odds * 100, 0)}%</b>. Likely range after {years} years:{' '}
            <span className="tabular">
              {inr(result.last.p10)} (bad case) · {inr(result.last.p50)} (middle) · {inr(result.last.p90)} (good case)
            </span>
            , from {inr(result.last.invested)} put in.
          </div>
          <p className="text-[12px] text-faint">
            2,000 simulated paths at {num(expected, 1)}% a year (your assumption above) with this fund's own 3-year volatility of {num((vol ?? 0) * 100, 1)}%.
            Bad / good case = 10th / 90th percentile. Not a promise of returns.
          </p>
        </div>
      )}
    </div>
  )
}
