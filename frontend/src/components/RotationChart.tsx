import { useMemo } from 'react'
import { CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import type { Quadrant } from '../api/listings'
import { num } from '../lib/format'

/** Shared by Sector rotation and Fund rotation: one palette, one quadrant language. */
export const ROTATION_COLORS = ['#6d8cff', '#34d399', '#fbbf24', '#f472b6', '#22d3ee', '#a78bfa', '#fb923c', '#94a3b8', '#ef4444', '#10b981', '#eab308', '#8b5cf6', '#06b6d4', '#f97316', '#84cc16']

export const rotationQuadrants = (bench: string): Record<Quadrant, { label: string; note: string; className: string }> => ({
  leading: { label: 'Leading', note: `Beating the ${bench} and still gaining`, className: 'text-up' },
  weakening: { label: 'Weakening', note: 'Still ahead but losing steam', className: 'text-warn' },
  lagging: { label: 'Lagging', note: `Behind the ${bench} and still slipping`, className: 'text-down' },
  improving: { label: 'Improving', note: 'Behind but catching up', className: 'text-accent-fg' },
})

type Point = { ratio: number; momentum: number }

/** Relative rotation graph (RS-Ratio vs RS-Momentum around 100). Only the
 * focused series draws its trail; the rest show just their latest dot. */
export default function RotationChart({ series, focus }: { series: { name: string; tail: Point[] }[]; focus: string | null }) {
  const domain = useMemo(() => {
    const pts = series.flatMap((s) => s.tail)
    const span = (k: 'ratio' | 'momentum') => Math.max(1, ...pts.map((p) => Math.abs(p[k] - 100))) * 1.1
    return { x: span('ratio'), y: span('momentum') }
  }, [series])

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
          <ReferenceArea x1={100} x2={100 + domain.x} y1={100} y2={100 + domain.y} fill="var(--color-up)" fillOpacity={0.06} />
          <ReferenceArea x1={100} x2={100 + domain.x} y1={100 - domain.y} y2={100} fill="var(--color-warn)" fillOpacity={0.06} />
          <ReferenceArea x1={100 - domain.x} x2={100} y1={100 - domain.y} y2={100} fill="var(--color-down)" fillOpacity={0.06} />
          <ReferenceArea x1={100 - domain.x} x2={100} y1={100} y2={100 + domain.y} fill="var(--color-accent)" fillOpacity={0.06} />
          <CartesianGrid stroke="var(--color-line)" />
          <ReferenceLine x={100} stroke="var(--color-line-strong)" />
          <ReferenceLine y={100} stroke="var(--color-line-strong)" />
          <XAxis type="number" dataKey="ratio" domain={[100 - domain.x, 100 + domain.x]} tickFormatter={(v) => num(v, 1)}
            tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
            label={{ value: 'Relative strength →', position: 'insideBottom', offset: -10, fill: 'var(--color-faint)', fontSize: 11 }} />
          <YAxis type="number" dataKey="momentum" domain={[100 - domain.y, 100 + domain.y]} tickFormatter={(v) => num(v, 1)} width={44}
            tick={{ fill: 'var(--color-faint)', fontSize: 11 }} />
          <Tooltip
            cursor={false}
            contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
            formatter={(v, key) => [num(Number(v), 2), key === 'ratio' ? 'RS-Ratio' : 'RS-Momentum']}
            labelFormatter={() => ''}
          />
          {series.map((s, i) => {
            const dim = focus != null && focus !== s.name
            const color = ROTATION_COLORS[i % ROTATION_COLORS.length]
            const points = focus === s.name ? s.tail : s.tail.slice(-1)
            return (
              <Scatter key={s.name} name={s.name} data={points} line={focus === s.name ? { stroke: color, strokeOpacity: 0.8 } : false}
                fill={color} fillOpacity={dim ? 0.15 : 1} isAnimationActive={false}
                shape={(props: { cx?: number; cy?: number; index?: number }) => {
                  const last = props.index === points.length - 1
                  return <circle cx={props.cx} cy={props.cy} r={last ? 5 : 2} fill={color} fillOpacity={dim ? 0.15 : last ? 1 : 0.6} />
                }} />
            )
          })}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}
