import { cx } from '../../lib/cx'

/** One number in a stats grid (Backtest, Journal). */
export default function StatTile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'up' | 'down' }) {
  return (
    <div className="bg-surface px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx('tabular text-sm font-semibold', tone === 'up' && 'text-up', tone === 'down' && 'text-down')}>{value}</div>
      {sub && <div className="text-[12px] text-faint">{sub}</div>}
    </div>
  )
}
