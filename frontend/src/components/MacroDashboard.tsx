import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts'
import { getMacro, type MacroData, type MacroSeries } from '../api/macro'
import { num } from '../lib/format'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'

import InsightLoader from './InsightLoader'
import YieldCurve from './YieldCurve'

const GROUPS: Array<{ key: MacroSeries['group']; label: string }> = [
  { key: 'india', label: 'India' },
  { key: 'us', label: 'United States' },
  { key: 'global', label: 'Global' },
]

function fmt(s: MacroSeries, v: number | null | undefined, signed = false): string {
  if (v == null) return '—'
  const body = num(v, 2)
  const sign = signed && v > 0 ? '+' : ''
  if (s.unit === '%' || s.unit === 'pts') return `${sign}${body}${s.unit === '%' ? '%' : ''}`
  return `${sign}${s.unit}${body}`
}

/** Key rates, inflation, currency and oil, with 3-year sparklines. */
export default function MacroDashboard() {
  const { data, error, at } = useInsight<MacroData>((signal) => getMacro(signal), [], DAILY_EVERY)

  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Macro backdrop</h2>
          <p className="text-xs text-muted">Rates, inflation, rupee and oil: the forces that move the whole market</p>
          <InsightLive at={at} daily="Daily and monthly series" />
        </div>
      </div>
      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Fetching India indicators…', 'Fetching US indicators…', 'Fetching global indicators…']} />}
        {data && (
          <>
            {data.signals.us_curve_inverted && (
              <p className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
                The US yield curve is inverted (2-year above 10-year), a pattern that has preceded most US recessions.
              </p>
            )}
            {GROUPS.map((g) => {
              const items = data.series.filter((s) => s.group === g.key)
              if (!items.length) return null
              return (
                <div key={g.key}>
                  <div className="mb-2 text-xs font-medium text-muted">{g.label}</div>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {items.map((s) => <Tile key={s.id} s={s} />)}
                  </div>
                </div>
              )
            })}
            <YieldCurve />
            <p className="text-[12px] text-faint">
              Source: {data.source}. Monthly series lag by a few weeks.{data.failed.length ? ` Unavailable now: ${data.failed.join(', ')}.` : ''}
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function Tile({ s }: { s: MacroSeries }) {
  return (
    <div className="rounded-lg bg-canvas px-3 py-2" title={s.note}>
      <div className="truncate text-xs text-muted">{s.label}</div>
      <div className="flex items-end justify-between gap-2">
        <div>
          <div className="tabular text-lg font-semibold">{fmt(s, s.value)}</div>
          <div className="tabular text-[11px] text-faint">
            1y <span className="text-fg">{fmt(s, s.change_1y, true)}</span>
          </div>
          <div className="text-[11px] text-faint">as of {s.date}</div>
        </div>
        <div className="h-10 w-24 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={s.spark} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
              <YAxis hide domain={['auto', 'auto']} />
              <Area type="monotone" dataKey="value" stroke="var(--color-accent)" strokeWidth={1.5} fill="var(--color-accent)" fillOpacity={0.12} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
