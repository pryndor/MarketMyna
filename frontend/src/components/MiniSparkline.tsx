import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts'

/** The small trend line at the end of a market / commodity row. */
export default function MiniSparkline({ values, up }: { values: number[]; up: boolean }) {
  const color = up ? 'var(--color-up)' : 'var(--color-down)'
  return (
    <div className="h-10 w-16 shrink-0 sm:w-20">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={values.map((v) => ({ v }))} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <YAxis hide domain={['auto', 'auto']} />
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill={color} fillOpacity={0.12} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
