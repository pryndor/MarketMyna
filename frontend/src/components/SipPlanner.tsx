import { useEffect, useState } from 'react'
import { SipDayCard } from './SipDays'
import SipGoal from './SipGoal'
import { getFundSip, type SipParams, type SipResult } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, pct } from '../lib/format'
import { Field, Input, Segmented, Skeleton } from './ui'

const YEARS = [
  { value: '1', label: '1Y' },
  { value: '3', label: '3Y' },
  { value: '5', label: '5Y' },
  { value: '10', label: '10Y' },
]

function inr(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
}

function NumberField({ label, value, onChange, min, max, step }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number
}) {
  const [text, setText] = useState(String(value))
  useEffect(() => setText(String(value)), [value])
  return (
    <Field label={label}>
      <Input
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step ?? 1}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          const n = Number(e.target.value)
          if (e.target.value !== '' && Number.isFinite(n) && n >= min && n <= max) onChange(n)
        }}
      />
    </Field>
  )
}

/** SIP backtest on the fund's real NAV, SIP vs lumpsum, SIP-day effect and a step-up projection. */
export default function SipPlanner({ code }: { code: string }) {
  const [params, setParams] = useState<SipParams>({ monthly: 5000, years: 5, day: 5, step_up: 10, expected: 12, horizon: 10 })
  const [data, setData] = useState<SipResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const set = (patch: Partial<SipParams>) => setParams((p) => ({ ...p, ...patch }))

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const t = setTimeout(() => {
      getFundSip(code, params)
        .then((r) => {
          if (cancelled) return
          setData(r)
          setError(null)
        })
        .catch((err) => !cancelled && setError(errorMessage(err)))
        .finally(() => !cancelled && setLoading(false))
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [code, params])

  const bt = data?.backtest
  const su = data?.step_up

  return (
    <section className="space-y-4 border-t border-line pt-5">
      <div>
        <h3 className="text-sm font-semibold">SIP planner</h3>
        <p className="mt-0.5 text-xs text-muted">What a monthly SIP in this fund would be worth today, from its real NAV history.</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <NumberField label="Monthly SIP (₹)" value={params.monthly} min={100} max={10_000_000} step={500} onChange={(monthly) => set({ monthly })} />
        <NumberField label="SIP day" value={params.day} min={1} max={28} onChange={(day) => set({ day })} />
        <Field label="Over the last" className="col-span-2">
          <Segmented options={YEARS} value={String(params.years)} onChange={(v) => set({ years: Number(v) })} size="sm" />
        </Field>
      </div>

      {error ? (
        <p className="text-xs text-down">SIP backtest unavailable: {error}</p>
      ) : !bt || (loading && !data) ? (
        <Skeleton className="h-40 w-full" />
      ) : bt.error ? (
        <p className="text-xs text-muted">{bt.error}</p>
      ) : (
        <div className={cx('space-y-4 transition-opacity', loading && 'opacity-60')}>
          <div className="grid gap-3 sm:grid-cols-2">
            {([
              ['sip', `SIP of ${inr(bt.monthly)} a month`, bt.sip.value, bt.sip.gain_pct, `XIRR ${pct(bt.sip.xirr_pct)}`, `${bt.sip.installments} instalments`],
              ['lumpsum', `Lumpsum on ${bt.lumpsum.date}`, bt.lumpsum.value, bt.lumpsum.gain_pct, `CAGR ${pct(bt.lumpsum.cagr_pct)}`, 'same total, invested at once'],
            ] as const).map(([key, title, value, gain, rate, sub]) => (
              <div key={key} className={cx('rounded-lg border p-3', bt.winner === key ? 'border-up/50 bg-up-soft/40' : 'border-line bg-canvas')}>
                <div className="flex items-center justify-between gap-2 text-xs text-muted">
                  <span>{title}</span>
                  {bt.winner === key && <span className="font-semibold text-up">Ahead</span>}
                </div>
                <div className="tabular mt-1 text-lg font-semibold">{inr(value)}</div>
                <div className="tabular text-xs">
                  <span className={gain >= 0 ? 'text-up' : 'text-down'}>{pct(gain)}</span>
                  <span className="text-muted"> · {rate}</span>
                </div>
                <div className="mt-1 text-xs text-faint">Invested {inr(bt.sip.invested)} · {sub}</div>
              </div>
            ))}
          </div>

          {bt.note && <p className="text-xs text-warn">{bt.note}</p>}
        </div>
      )}

      <SipDayCard market="india" kind="mf" symbol={code} highlight={params.day} />

      <div className="space-y-3 rounded-lg bg-canvas p-4">
        <div className="text-xs font-medium text-muted">Step-up projection</div>
        <div className="grid grid-cols-3 gap-3">
          <NumberField label="Step-up %/yr" value={params.step_up} min={0} max={100} onChange={(step_up) => set({ step_up })} />
          <NumberField label="Return %/yr" value={params.expected} min={-50} max={50} step={0.5} onChange={(expected) => set({ expected })} />
          <NumberField label="Years" value={params.horizon} min={1} max={40} onChange={(horizon) => set({ horizon })} />
        </div>
        {su ? (
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-xs text-faint">With {su.step_pct}% step-up</div>
              <div className="tabular font-semibold">{inr(su.corpus)}</div>
              <div className="tabular text-xs text-muted">invested {inr(su.invested)}</div>
            </div>
            <div>
              <div className="text-xs text-faint">Flat SIP</div>
              <div className="tabular font-semibold">{inr(su.flat_corpus)}</div>
              <div className="tabular text-xs text-muted">invested {inr(su.flat_invested)}</div>
            </div>
          </div>
        ) : (
          <Skeleton className="h-10 w-full" />
        )}
        <p className="text-xs text-faint">Projection assumes a steady return; real returns vary. Not investment advice.</p>
      </div>

      <SipGoal code={code} monthly={params.monthly} expected={params.expected} />
    </section>
  )
}
