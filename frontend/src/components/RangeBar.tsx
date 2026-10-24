import { compact } from '../lib/format'

/** Where today's price sits inside the 52-week range. */
export default function RangeBar({ low, high, value }: { low?: number | null; high?: number | null; value?: number | null }) {
  if (low == null || high == null || value == null || high <= low) return <div className="text-end text-faint">—</div>
  const pos = Math.max(0, Math.min(100, ((value - low) / (high - low)) * 100))
  return (
    <div className="ms-auto w-28" title={`52w low ${low} · high ${high}`}>
      <div className="relative h-1 rounded-full bg-line">
        <span className="absolute top-1/2 h-2.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-accent" style={{ left: `${pos}%` }} />
      </div>
      <div className="tabular mt-1 flex justify-between text-[12px] text-faint">
        <span>{compact(low)}</span>
        <span>{compact(high)}</span>
      </div>
    </div>
  )
}
