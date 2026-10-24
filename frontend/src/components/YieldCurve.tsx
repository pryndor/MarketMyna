import { useEffect, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getYieldCurve, type YieldCurve as Curve } from '../api/macro'
import { cx } from '../lib/cx'
import { num } from '../lib/format'
import { Skeleton } from './ui'

const SHAPE = {
  normal: { text: 'Normal (upward sloping)', className: 'bg-up-soft text-up' },
  flat: { text: 'Flat', className: 'bg-warn-soft text-warn' },
  inverted: { text: 'Inverted', className: 'bg-down-soft text-down' },
}

/** US Treasury curve now vs 1 month and 1 year ago. */
export default function YieldCurve() {
  const [data, setData] = useState<Curve | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getYieldCurve(controller.signal)
      .then(setData)
      .catch(() => !controller.signal.aborted && setFailed(true))
    return () => controller.abort()
  }, [])

  if (failed || (data && !data.points.length)) return null
  const shape = data?.shape ? SHAPE[data.shape.label] : null

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-medium text-muted">US Treasury yield curve{data?.as_of ? ` · ${data.as_of}` : ''}</div>
        {shape && data?.shape && (
          <span className={cx('rounded-md px-2 py-0.5 text-xs', shape.className)}>
            {shape.text} · 10Y − 3M {data.shape.spread_10y_3m > 0 ? '+' : ''}{num(data.shape.spread_10y_3m)} pts
          </span>
        )}
      </div>
      <div className="h-56 rounded-lg bg-canvas p-2">
        {!data ? (
          <Skeleton className="h-full w-full" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--color-line)" vertical={false} />
              <XAxis dataKey="tenor" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} interval={0} minTickGap={0} />
              <YAxis
                domain={['auto', 'auto']}
                width={40}
                tickFormatter={(v: number) => `${num(v, 1)}%`}
                tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                formatter={(v) => `${num(Number(v))}%`}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line name="Now" dataKey="now" stroke="var(--color-accent)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
              <Line name="1 month ago" dataKey="month_ago" stroke="var(--color-muted)" strokeWidth={1.25} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              <Line name="1 year ago" dataKey="year_ago" stroke="var(--color-faint)" strokeWidth={1.25} strokeDasharray="1 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <p className="mt-1.5 text-[12px] text-faint">
        Short-term yields follow the central bank; long-term ones price growth and inflation. A curve that turns inverted
        (short above long) has preceded most US recessions. No free daily curve exists for India.
      </p>
    </div>
  )
}
